//! Native tool executors — Calculator and DateTimeTool.
//!
//! Tools are pure functions that execute locally (no LLM call).
//! When a `use_tool` step references a known tool, the runner
//! intercepts it and calls the executor directly.
//!
//! Supported tools:
//!   - Calculator: safe arithmetic expression evaluator
//!   - DateTimeTool: current date/time/timestamp queries

use std::time::{SystemTime, UNIX_EPOCH};

/// Result of a tool execution.
#[derive(Debug)]
pub struct ToolResult {
    pub success: bool,
    pub output: String,
    pub tool_name: String,
}

/// Dispatch a tool call by name. Returns `None` if the tool is not a native executor.
pub fn dispatch(tool_name: &str, argument: &str) -> Option<ToolResult> {
    match tool_name {
        "Calculator" => Some(calculator_execute(argument)),
        "DateTimeTool" => Some(datetime_execute(argument)),
        _ => None, // Not a native tool — fall through to LLM
    }
}

// ── Calculator ──────────────────────────────────────────────────────────────

/// Safe arithmetic expression evaluator.
///
/// Supports: +, -, *, /, % (mod), ** (power), parentheses,
/// constants (pi, e), and functions (sqrt, abs, round, sin, cos, tan,
/// log, ln, ceil, floor, pow, min, max).
pub fn calculator_execute(expression: &str) -> ToolResult {
    let expr = expression.trim();
    if expr.is_empty() {
        return ToolResult {
            success: false,
            output: "Empty expression".to_string(),
            tool_name: "Calculator".to_string(),
        };
    }

    match eval_expr(expr) {
        Ok(val) => {
            // Format: remove trailing zeros for clean output
            let formatted = if val.fract() == 0.0 && val.abs() < 1e15 {
                format!("{}", val as i64)
            } else {
                format!("{}", val)
            };
            ToolResult {
                success: true,
                output: formatted,
                tool_name: "Calculator".to_string(),
            }
        }
        Err(e) => ToolResult {
            success: false,
            output: format!("Calculator error: {e}"),
            tool_name: "Calculator".to_string(),
        },
    }
}

// ── Calculator parser (recursive descent) ───────────────────────────────────

struct CalcParser<'a> {
    input: &'a [u8],
    pos: usize,
}

impl<'a> CalcParser<'a> {
    fn new(input: &'a str) -> Self {
        Self {
            input: input.as_bytes(),
            pos: 0,
        }
    }

    fn skip_ws(&mut self) {
        while self.pos < self.input.len() && self.input[self.pos].is_ascii_whitespace() {
            self.pos += 1;
        }
    }

    fn peek(&mut self) -> Option<u8> {
        self.skip_ws();
        self.input.get(self.pos).copied()
    }

    fn consume(&mut self, expected: u8) -> bool {
        self.skip_ws();
        if self.pos < self.input.len() && self.input[self.pos] == expected {
            self.pos += 1;
            true
        } else {
            false
        }
    }

    /// expr = term (('+' | '-') term)*
    fn parse_expr(&mut self) -> Result<f64, String> {
        let mut result = self.parse_term()?;
        loop {
            self.skip_ws();
            if self.consume(b'+') {
                result += self.parse_term()?;
            } else if self.consume(b'-') {
                result -= self.parse_term()?;
            } else {
                break;
            }
        }
        Ok(result)
    }

    /// term = power (('*' | '/' | '%') power)*
    fn parse_term(&mut self) -> Result<f64, String> {
        let mut result = self.parse_power()?;
        loop {
            self.skip_ws();
            if self.consume(b'*') {
                if self.consume(b'*') {
                    // ** is power — put it back and let power handle it
                    self.pos -= 2;
                    break;
                }
                result *= self.parse_power()?;
            } else if self.consume(b'/') {
                let divisor = self.parse_power()?;
                if divisor == 0.0 {
                    return Err("Division by zero".to_string());
                }
                result /= divisor;
            } else if self.consume(b'%') {
                let modulus = self.parse_power()?;
                if modulus == 0.0 {
                    return Err("Modulo by zero".to_string());
                }
                result %= modulus;
            } else {
                break;
            }
        }
        Ok(result)
    }

    /// power = unary ('**' unary)*
    fn parse_power(&mut self) -> Result<f64, String> {
        let base = self.parse_unary()?;
        self.skip_ws();
        if self.pos + 1 < self.input.len()
            && self.input[self.pos] == b'*'
            && self.input[self.pos + 1] == b'*'
        {
            self.pos += 2;
            let exp = self.parse_power()?; // right-associative
            Ok(base.powf(exp))
        } else {
            Ok(base)
        }
    }

    /// unary = '-' unary | '+' unary | atom
    fn parse_unary(&mut self) -> Result<f64, String> {
        self.skip_ws();
        if self.consume(b'-') {
            Ok(-self.parse_unary()?)
        } else if self.consume(b'+') {
            self.parse_unary()
        } else {
            self.parse_atom()
        }
    }

    /// atom = number | '(' expr ')' | function '(' args ')' | constant
    fn parse_atom(&mut self) -> Result<f64, String> {
        self.skip_ws();

        // Parenthesized expression
        if self.consume(b'(') {
            let val = self.parse_expr()?;
            if !self.consume(b')') {
                return Err("Missing closing parenthesis".to_string());
            }
            return Ok(val);
        }

        // Number
        if self.pos < self.input.len()
            && (self.input[self.pos].is_ascii_digit() || self.input[self.pos] == b'.')
        {
            return self.parse_number();
        }

        // Identifier (function or constant)
        if self.pos < self.input.len() && self.input[self.pos].is_ascii_alphabetic() {
            let name = self.parse_ident();
            return self.resolve_ident(&name);
        }

        Err(format!(
            "Unexpected character at position {}",
            self.pos
        ))
    }

    fn parse_number(&mut self) -> Result<f64, String> {
        let start = self.pos;
        while self.pos < self.input.len()
            && (self.input[self.pos].is_ascii_digit() || self.input[self.pos] == b'.')
        {
            self.pos += 1;
        }
        // Handle scientific notation: 1e10, 2.5e-3
        if self.pos < self.input.len()
            && (self.input[self.pos] == b'e' || self.input[self.pos] == b'E')
        {
            self.pos += 1;
            if self.pos < self.input.len()
                && (self.input[self.pos] == b'+' || self.input[self.pos] == b'-')
            {
                self.pos += 1;
            }
            while self.pos < self.input.len() && self.input[self.pos].is_ascii_digit() {
                self.pos += 1;
            }
        }
        let s = std::str::from_utf8(&self.input[start..self.pos])
            .map_err(|_| "Invalid UTF-8 in number")?;
        s.parse::<f64>()
            .map_err(|_| format!("Invalid number: '{s}'"))
    }

    fn parse_ident(&mut self) -> String {
        let start = self.pos;
        while self.pos < self.input.len()
            && (self.input[self.pos].is_ascii_alphanumeric() || self.input[self.pos] == b'_')
        {
            self.pos += 1;
        }
        String::from_utf8_lossy(&self.input[start..self.pos]).to_string()
    }

    fn resolve_ident(&mut self, name: &str) -> Result<f64, String> {
        // Constants
        match name {
            "pi" | "PI" => return Ok(std::f64::consts::PI),
            "e" | "E" => return Ok(std::f64::consts::E),
            "tau" | "TAU" => return Ok(std::f64::consts::TAU),
            "inf" => return Ok(f64::INFINITY),
            _ => {}
        }

        // Functions
        self.skip_ws();
        if !self.consume(b'(') {
            return Err(format!("Unknown identifier: '{name}'"));
        }

        let args = self.parse_args()?;

        if !self.consume(b')') {
            return Err(format!("Missing ')' after {name}(...)"));
        }

        match (name, args.len()) {
            ("sqrt", 1) => Ok(args[0].sqrt()),
            ("abs", 1) => Ok(args[0].abs()),
            ("round", 1) => Ok(args[0].round()),
            ("ceil", 1) => Ok(args[0].ceil()),
            ("floor", 1) => Ok(args[0].floor()),
            ("sin", 1) => Ok(args[0].sin()),
            ("cos", 1) => Ok(args[0].cos()),
            ("tan", 1) => Ok(args[0].tan()),
            ("asin", 1) => Ok(args[0].asin()),
            ("acos", 1) => Ok(args[0].acos()),
            ("atan", 1) => Ok(args[0].atan()),
            ("log", 1) | ("log10", 1) => Ok(args[0].log10()),
            ("ln", 1) => Ok(args[0].ln()),
            ("log2", 1) => Ok(args[0].log2()),
            ("exp", 1) => Ok(args[0].exp()),
            ("pow", 2) => Ok(args[0].powf(args[1])),
            ("min", 2) => Ok(args[0].min(args[1])),
            ("max", 2) => Ok(args[0].max(args[1])),
            ("atan2", 2) => Ok(args[0].atan2(args[1])),
            _ => Err(format!("Unknown function: '{name}' with {} args", args.len())),
        }
    }

    fn parse_args(&mut self) -> Result<Vec<f64>, String> {
        let mut args = Vec::new();
        self.skip_ws();
        if self.peek() == Some(b')') {
            return Ok(args);
        }
        args.push(self.parse_expr()?);
        while self.consume(b',') {
            args.push(self.parse_expr()?);
        }
        Ok(args)
    }
}

fn eval_expr(expr: &str) -> Result<f64, String> {
    let mut parser = CalcParser::new(expr);
    let result = parser.parse_expr()?;
    parser.skip_ws();
    if parser.pos < parser.input.len() {
        return Err(format!(
            "Unexpected trailing characters at position {}",
            parser.pos
        ));
    }
    if result.is_nan() {
        return Err("Result is NaN".to_string());
    }
    Ok(result)
}

// ── DateTimeTool ────────────────────────────────────────────────────────────

/// Current date/time queries using system time (UTC).
///
/// Supported queries: now, today, timestamp, year, month, day, weekday, iso,
/// hour, minute, second, date, time.
pub fn datetime_execute(query: &str) -> ToolResult {
    let query = query.trim().to_lowercase();

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();

    let secs = now.as_secs();
    let (year, month, day, hour, min, sec, weekday) = unix_to_utc(secs);

    let output = match query.as_str() {
        "now" | "iso" | "datetime" => format!(
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
            year, month, day, hour, min, sec
        ),
        "today" | "date" => format!("{:04}-{:02}-{:02}", year, month, day),
        "time" => format!("{:02}:{:02}:{:02}Z", hour, min, sec),
        "timestamp" | "unix" | "epoch" => format!("{}", secs),
        "year" => format!("{}", year),
        "month" => format!("{}", month),
        "day" => format!("{}", day),
        "hour" => format!("{}", hour),
        "minute" => format!("{}", min),
        "second" => format!("{}", sec),
        "weekday" => weekday_name(weekday).to_string(),
        _ => format!(
            "Unknown query '{}'. Supported: now, today, timestamp, year, month, day, weekday, iso, time, hour, minute, second",
            query
        ),
    };

    ToolResult {
        success: true,
        output,
        tool_name: "DateTimeTool".to_string(),
    }
}

/// Convert UNIX timestamp to (year, month, day, hour, min, sec, weekday).
/// weekday: 0=Sunday, 1=Monday, ..., 6=Saturday.
fn unix_to_utc(secs: u64) -> (i32, u32, u32, u32, u32, u32, u32) {
    let days = (secs / 86400) as i64;
    let time_of_day = secs % 86400;

    let hour = (time_of_day / 3600) as u32;
    let min = ((time_of_day % 3600) / 60) as u32;
    let sec = (time_of_day % 60) as u32;

    // Weekday: Jan 1, 1970 was Thursday (4)
    let weekday = ((days + 4) % 7) as u32;

    // Civil date from days since epoch (algorithm from Howard Hinnant)
    let z = days + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u32;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = (yoe as i64 + era * 400) as i32;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if m <= 2 { y + 1 } else { y };

    (year, m, d, hour, min, sec, weekday)
}

fn weekday_name(weekday: u32) -> &'static str {
    match weekday {
        0 => "Sunday",
        1 => "Monday",
        2 => "Tuesday",
        3 => "Wednesday",
        4 => "Thursday",
        5 => "Friday",
        6 => "Saturday",
        _ => "Unknown",
    }
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // Calculator tests

    #[test]
    fn calc_basic_arithmetic() {
        assert_eq!(eval_expr("2 + 3").unwrap(), 5.0);
        assert_eq!(eval_expr("10 - 4").unwrap(), 6.0);
        assert_eq!(eval_expr("3 * 7").unwrap(), 21.0);
        assert_eq!(eval_expr("20 / 4").unwrap(), 5.0);
    }

    #[test]
    fn calc_operator_precedence() {
        assert_eq!(eval_expr("2 + 3 * 4").unwrap(), 14.0);
        assert_eq!(eval_expr("(2 + 3) * 4").unwrap(), 20.0);
    }

    #[test]
    fn calc_power() {
        assert_eq!(eval_expr("2 ** 10").unwrap(), 1024.0);
        assert_eq!(eval_expr("3 ** 2").unwrap(), 9.0);
    }

    #[test]
    fn calc_modulo() {
        assert_eq!(eval_expr("17 % 5").unwrap(), 2.0);
    }

    #[test]
    fn calc_unary_minus() {
        assert_eq!(eval_expr("-5").unwrap(), -5.0);
        assert_eq!(eval_expr("-3 + 7").unwrap(), 4.0);
        assert_eq!(eval_expr("-(2 + 3)").unwrap(), -5.0);
    }

    #[test]
    fn calc_constants() {
        assert!((eval_expr("pi").unwrap() - std::f64::consts::PI).abs() < 1e-10);
        assert!((eval_expr("e").unwrap() - std::f64::consts::E).abs() < 1e-10);
    }

    #[test]
    fn calc_functions() {
        assert_eq!(eval_expr("sqrt(16)").unwrap(), 4.0);
        assert_eq!(eval_expr("abs(-5)").unwrap(), 5.0);
        assert_eq!(eval_expr("round(3.7)").unwrap(), 4.0);
        assert_eq!(eval_expr("ceil(3.2)").unwrap(), 4.0);
        assert_eq!(eval_expr("floor(3.8)").unwrap(), 3.0);
        assert_eq!(eval_expr("pow(2, 8)").unwrap(), 256.0);
        assert_eq!(eval_expr("min(3, 7)").unwrap(), 3.0);
        assert_eq!(eval_expr("max(3, 7)").unwrap(), 7.0);
    }

    #[test]
    fn calc_trig() {
        assert!((eval_expr("sin(0)").unwrap()).abs() < 1e-10);
        assert!((eval_expr("cos(0)").unwrap() - 1.0).abs() < 1e-10);
    }

    #[test]
    fn calc_logarithm() {
        assert!((eval_expr("log(100)").unwrap() - 2.0).abs() < 1e-10);
        assert!((eval_expr("ln(e)").unwrap() - 1.0).abs() < 1e-10);
    }

    #[test]
    fn calc_nested() {
        assert_eq!(eval_expr("sqrt(pow(3, 2) + pow(4, 2))").unwrap(), 5.0);
    }

    #[test]
    fn calc_scientific_notation() {
        assert_eq!(eval_expr("1e3").unwrap(), 1000.0);
        assert_eq!(eval_expr("2.5e2").unwrap(), 250.0);
    }

    #[test]
    fn calc_division_by_zero() {
        assert!(eval_expr("1 / 0").is_err());
    }

    #[test]
    fn calc_empty_expression() {
        let r = calculator_execute("");
        assert!(!r.success);
    }

    #[test]
    fn calc_invalid_expression() {
        assert!(eval_expr("2 +").is_err());
    }

    #[test]
    fn calc_integer_output() {
        let r = calculator_execute("2 + 3");
        assert!(r.success);
        assert_eq!(r.output, "5");
    }

    #[test]
    fn calc_float_output() {
        let r = calculator_execute("1 / 3");
        assert!(r.success);
        assert!(r.output.starts_with("0.333"));
    }

    // DateTimeTool tests

    #[test]
    fn datetime_now_iso_format() {
        let r = datetime_execute("now");
        assert!(r.success);
        assert!(r.output.contains('T'));
        assert!(r.output.ends_with('Z'));
    }

    #[test]
    fn datetime_today() {
        let r = datetime_execute("today");
        assert!(r.success);
        assert_eq!(r.output.len(), 10); // YYYY-MM-DD
        assert!(r.output.contains('-'));
    }

    #[test]
    fn datetime_timestamp() {
        let r = datetime_execute("timestamp");
        assert!(r.success);
        let ts: u64 = r.output.parse().expect("should be a number");
        assert!(ts > 1700000000); // After ~2023
    }

    #[test]
    fn datetime_year() {
        let r = datetime_execute("year");
        assert!(r.success);
        let y: i32 = r.output.parse().expect("should be a number");
        assert!(y >= 2024);
    }

    #[test]
    fn datetime_weekday() {
        let r = datetime_execute("weekday");
        assert!(r.success);
        let valid = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
        assert!(valid.contains(&r.output.as_str()));
    }

    #[test]
    fn datetime_unknown_query() {
        let r = datetime_execute("foobar");
        assert!(r.success);
        assert!(r.output.contains("Unknown query"));
    }

    // Dispatch tests

    #[test]
    fn dispatch_calculator() {
        let r = dispatch("Calculator", "2 + 2");
        assert!(r.is_some());
        let r = r.unwrap();
        assert!(r.success);
        assert_eq!(r.output, "4");
    }

    #[test]
    fn dispatch_datetime() {
        let r = dispatch("DateTimeTool", "now");
        assert!(r.is_some());
        assert!(r.unwrap().success);
    }

    #[test]
    fn dispatch_unknown_tool() {
        assert!(dispatch("WebSearch", "query").is_none());
    }
}
