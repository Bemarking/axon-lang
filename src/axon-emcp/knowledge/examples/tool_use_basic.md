---
name: tool_use_basic
title: Flow that uses a tool with a declared backend
summary: Shows the canonical `tool` primitive — a named backend with effects, timeout, and provider — invoked from a step via `apply:`.
topic: composition
primitives:
  - persona
  - flow
  - step
  - tool
---

// A step invokes a named tool via `apply:`. The tool declares its
// provider + effects + timeout once; every step that uses it
// inherits those constraints.

persona Translator {
    domain: ["translation"]
    tone: precise
    confidence_threshold: 0.9
    cite_sources: false
}

tool TranslationBackend {
    provider: openai
    effects:  <network>
    timeout:  30s
}

type Input  { text: String, target_lang: String }
type Output { text: String }

flow Translate(req: Input) -> Output {
    step Render {
        given: req
        apply: TranslationBackend
        ask: "Translate the input text into the target language."
        output: Output
    }
    return Render.output
}
