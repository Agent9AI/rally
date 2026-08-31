# Live Google media proof

These are byte-for-byte outputs from Rally's bounded Google media tool on
August 31, 2026. They are committed as reviewable evidence, not as mock demo
assets.

| Request | Google model | Output | Receipt |
|---|---|---|---|
| “Create the All Things Agentic Hackathon Song” | Lyria 3 Pro Preview | [Play or download the 69.96-second MP3](all-things-agentic-lyria-3-pro.mp3) | 44.1 kHz, 192 kbps, SHA-256 `bfd411fd939e9677d3abe143c6d2dbbde7f29c6c057f4d5cf803b12f54ea2f95` |
| “Create a smooth, soulful, human-feeling hip-hop version of the All Things Agentic Hackathon Song” | Lyria 3 Pro Preview | [▶ Play the 73.33-second GitHub stream](all-things-agentic-soulful-hip-hop-lyria-3-pro.mp4) · [Original MP3](all-things-agentic-soulful-hip-hop-lyria-3-pro.mp3) · [Exact prompt](all-things-agentic-soulful-hip-hop-prompt.md) | Original: 44.1 kHz MP3, SHA-256 `81733fbc55910407ebad963618b26b8d03f373a0e2c7cfdfbf301385dfcf146d` · Stream: H.264/AAC, SHA-256 `1899a6d98f008699ba4e22590f43de3c33dcd5a21fbd13c6cf6f468d24b2b4a9` |
| “Picture of a happy beagle in a sunlit office” | Gemini 2.5 Flash Image | [Open the 1024×1024 PNG](beagle-gemini-image.png) | SHA-256 `5066a8d52d1fd81d772b0f52b726c3206f5c2ca11be3a0c8b16150f373bf87e5` |

![Live Gemini image output: a happy beagle in a sunlit office](beagle-gemini-image.png)

The MP4 is a deterministic H.264/AAC presentation wrapper around the verified
MP3, added only because GitHub supports native video streaming but not an
inline MP3 player. It is not claimed as another model generation.

The same runtime path writes the artifact into the isolated run workspace.
Rally's normal checklist and independent-verification rule still govern whether
the run may complete. On completion, Resend receives a bounded attachment; an
image also receives a CID so compatible mail clients show it inline without
removing the downloadable file. A reply in the same thread creates a revision
item and preserves prior approvals.

The non-secret machine receipt is in
[`generation-receipt.json`](generation-receipt.json). Google first rejected
full-name creative copy through its safety filter; Rally retained no failed
artifact, used the safer first-name wording requested by the operator, and
recorded only the successful output here.
