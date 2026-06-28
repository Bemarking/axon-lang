//! §Fase 71.b — the runtime for the `window` temporal execution guard (§71.a).
//!
//! Pure, total, timezone-aware functions over an [`IRWindow`]. The frontend
//! only FORMAT-checks the timezone string (it is zero-dependency); here we do
//! the authoritative IANA resolution + the DST-correct day/hour membership math
//! via `chrono-tz`. Every decision is a pure function of `(now, the window, the
//! tz-database version)` — the §71 doctrine `axon://logic/time_is_an_explicit_input`.
//!
//! Granularity is the hour (the `window` grammar's `hours: 9..18` are inclusive
//! 0–23 bounds). The `exclude:` holiday set is §71.e and is ignored here.

use chrono::{DateTime, Datelike, Duration, TimeZone, Timelike, Utc, Weekday};
use chrono_tz::Tz;

use crate::ir_nodes::IRWindow;

/// Resolve an IANA timezone name → [`Tz`]. `None` for an unknown name — this is
/// the AUTHORITATIVE membership check the frontend's format check defers to.
pub fn parse_tz(name: &str) -> Option<Tz> {
    name.trim().parse::<Tz>().ok()
}

/// Map a weekday name (`Mon`..`Sun`) to a chrono [`Weekday`].
fn weekday_of(name: &str) -> Option<Weekday> {
    Some(match name {
        "Mon" => Weekday::Mon,
        "Tue" => Weekday::Tue,
        "Wed" => Weekday::Wed,
        "Thu" => Weekday::Thu,
        "Fri" => Weekday::Fri,
        "Sat" => Weekday::Sat,
        "Sun" => Weekday::Sun,
        _ => return None,
    })
}

/// Is `wd` within the inclusive weekday range `[start, end]`? Supports wrap-
/// around: `Fri..Mon` covers Fri, Sat, Sun, Mon.
fn weekday_in_range(wd: Weekday, start: Weekday, end: Weekday) -> bool {
    let (w, s, e) = (
        wd.num_days_from_monday(),
        start.num_days_from_monday(),
        end.num_days_from_monday(),
    );
    if s <= e {
        s <= w && w <= e
    } else {
        w >= s || w <= e
    }
}

/// §Fase 71.b — is `now` (UTC) inside ANY allowed span of `window`, evaluated in
/// the window's timezone? `None` when the timezone is not a valid IANA name
/// (the caller fail-closes). A malformed span never matches (the §71.a type
/// checker rejects those at compile time).
pub fn is_in_window(now: DateTime<Utc>, window: &IRWindow) -> Option<bool> {
    let tz = parse_tz(&window.timezone)?;
    let local = now.with_timezone(&tz);
    let wd = local.weekday();
    let hour = local.hour() as i64;
    for span in &window.allow {
        let (Some(ds), Some(de)) = (weekday_of(&span.day_start), weekday_of(&span.day_end))
        else {
            continue;
        };
        if weekday_in_range(wd, ds, de) && span.hour_start <= hour && hour <= span.hour_end {
            return Some(true);
        }
    }
    Some(false)
}

/// §Fase 71.b — the next instant ≥ `now` that is inside the window (the input to
/// the §71.d defer ledger). Steps hour-by-hour, bounded to one week + a margin
/// (a non-empty window opens within 7 days). `None` if the timezone is invalid
/// or — defensively — no span opens within the bound. Hour-granular: the
/// returned instant is the top of the opening UTC hour.
pub fn next_window_open(now: DateTime<Utc>, window: &IRWindow) -> Option<DateTime<Utc>> {
    parse_tz(&window.timezone)?; // authoritative tz validation, once
    let mut probe = now
        .with_minute(0)
        .and_then(|t| t.with_second(0))
        .and_then(|t| t.with_nanosecond(0))?;
    for _ in 0..(8 * 24) {
        if is_in_window(probe, window) == Some(true) {
            return Some(probe);
        }
        probe += Duration::hours(1);
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir_nodes::{IRWindow, IRWindowSpan};

    fn span(d0: &str, d1: &str, h0: i64, h1: i64) -> IRWindowSpan {
        IRWindowSpan {
            day_start: d0.into(),
            day_end: d1.into(),
            hour_start: h0,
            hour_end: h1,
        }
    }
    fn window(tz: &str, allow: Vec<IRWindowSpan>) -> IRWindow {
        IRWindow {
            node_type: "window",
            source_line: 0,
            source_column: 0,
            name: "W".into(),
            timezone: tz.into(),
            allow,
            exclude: None,
            on_outside: "defer".into(),
        }
    }
    /// A UTC instant from an ISO-ish string `YYYY-MM-DDТHH:MM:SSZ`.
    fn utc(s: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
    }

    // ── tz resolution (the frontend↔runtime parity boundary) ─────────────

    #[test]
    fn parse_tz_accepts_real_iana_names_rejects_others() {
        for ok in ["America/Bogota", "UTC", "Europe/Madrid", "Asia/Kolkata", "America/New_York"] {
            assert!(parse_tz(ok).is_some(), "{ok} should resolve");
        }
        for bad in ["Bogota", "Mars/Olympus", "", "PST8PDT_typo"] {
            assert!(parse_tz(bad).is_none(), "{bad} should NOT resolve");
        }
    }

    #[test]
    fn invalid_tz_is_none_fail_closed() {
        let w = window("Bogota", vec![span("Mon", "Fri", 9, 18)]);
        assert_eq!(is_in_window(utc("2026-06-29T14:00:00Z"), &w), None);
        assert_eq!(next_window_open(utc("2026-06-29T14:00:00Z"), &w), None);
    }

    // ── is_in_window — the parity corpus ─────────────────────────────────

    #[test]
    fn window_parity_corpus() {
        // BusinessHours: America/Bogota (UTC-5, no DST), Mon..Fri 9..18.
        let bh = window("America/Bogota", vec![span("Mon", "Fri", 9, 18)]);
        // 2026-06-29 is a MONDAY. 14:00 UTC = 09:00 Bogota → in window.
        assert_eq!(is_in_window(utc("2026-06-29T14:00:00Z"), &bh), Some(true));
        // 13:00 UTC = 08:00 Bogota → before 9 → outside.
        assert_eq!(is_in_window(utc("2026-06-29T13:00:00Z"), &bh), Some(false));
        // 00:00 UTC Mon = 19:00 Sun Bogota → Sunday + late → outside.
        assert_eq!(is_in_window(utc("2026-06-29T00:00:00Z"), &bh), Some(false));
        // Saturday (2026-07-04) 17:00 UTC = 12:00 Bogota → weekend → outside.
        assert_eq!(is_in_window(utc("2026-07-04T17:00:00Z"), &bh), Some(false));

        // UTC window, all week, 0..23 → always in.
        let always = window("UTC", vec![span("Mon", "Sun", 0, 23)]);
        assert_eq!(is_in_window(utc("2026-01-01T03:00:00Z"), &always), Some(true));

        // Weekday wrap-around: Fri..Mon covers Saturday.
        let weekend = window("UTC", vec![span("Fri", "Mon", 0, 23)]);
        assert_eq!(is_in_window(utc("2026-07-04T12:00:00Z"), &weekend), Some(true)); // Sat
        assert_eq!(is_in_window(utc("2026-07-01T12:00:00Z"), &weekend), Some(false)); // Wed
    }

    #[test]
    fn dst_shifts_the_local_hour() {
        // New York 9..10, Mon..Sun. 13:00 UTC is 09:00 EDT (summer, UTC-4) →
        // in window; in winter (UTC-5) the same 13:00 UTC is 08:00 EST → out.
        let w = window("America/New_York", vec![span("Mon", "Sun", 9, 10)]);
        assert_eq!(is_in_window(utc("2026-07-06T13:00:00Z"), &w), Some(true)); // EDT
        assert_eq!(is_in_window(utc("2026-01-05T13:00:00Z"), &w), Some(false)); // EST
    }

    // ── next_window_open ─────────────────────────────────────────────────

    #[test]
    fn next_window_open_finds_the_next_opening() {
        let bh = window("America/Bogota", vec![span("Mon", "Fri", 9, 18)]);
        // 2026-06-29 08:00 Bogota = 13:00 UTC (Monday, before open). Next open
        // is 09:00 Bogota = 14:00 UTC the same day.
        let open = next_window_open(utc("2026-06-29T13:00:00Z"), &bh).unwrap();
        assert_eq!(open, utc("2026-06-29T14:00:00Z"));
        // If already inside, returns the current hour.
        let inside = next_window_open(utc("2026-06-29T15:30:00Z"), &bh).unwrap();
        assert_eq!(inside, utc("2026-06-29T15:00:00Z"));
    }
}
