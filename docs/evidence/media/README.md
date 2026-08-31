# Live Google media proof

These are byte-for-byte outputs from Rally's bounded Google media tool on
August 31, 2026. They are committed as reviewable evidence, not as mock demo
assets.

| Request | Google model | Output | Receipt |
|---|---|---|---|
| “Create the All Things Agentic Hackathon Song” | Lyria 3 Pro Preview | [Play or download the 69.96-second MP3](all-things-agentic-lyria-3-pro.mp3) | 44.1 kHz, 192 kbps, SHA-256 `bfd411fd939e9677d3abe143c6d2dbbde7f29c6c057f4d5cf803b12f54ea2f95` |
| “Create a smooth, soulful, human-feeling hip-hop version of the All Things Agentic Hackathon Song” | Lyria 3 Pro Preview | [▶ Play the 73.33-second GitHub stream](all-things-agentic-soulful-hip-hop-lyria-3-pro.mp4) · [Original MP3](all-things-agentic-soulful-hip-hop-lyria-3-pro.mp3) · [Exact prompt](all-things-agentic-soulful-hip-hop-prompt.md) | Original: 44.1 kHz MP3, SHA-256 `81733fbc55910407ebad963618b26b8d03f373a0e2c7cfdfbf301385dfcf146d` · Stream: 1200×630 H.264/AAC, SHA-256 `a2964ac56f3f07152b1eb339ad42d683e5cbca60420bf1c11c19a00c825dced9` |
| “Picture of a happy beagle in a sunlit office” | Gemini 2.5 Flash Image | [Open the 1024×1024 PNG](beagle-gemini-image.png) | SHA-256 `5066a8d52d1fd81d772b0f52b726c3206f5c2ca11be3a0c8b16150f373bf87e5` |
| Accountable-AI cover proof for the verified soulful hip-hop deliverable | Gemini 3.1 Flash Image (Nano Banana 2) | [Open the 1024×1024 PNG](rally-accountable-ai-nano-banana-2.png) | SHA-256 `39ea3f1a015db71cb71bec1f65f761cf8bd6fdddddb9efd590a20ead5727fa63` |

![Live Gemini image output: a happy beagle in a sunlit office](beagle-gemini-image.png)

![Live Nano Banana 2 output: accountable AI cover art](rally-accountable-ai-nano-banana-2.png)

The MP4 is a deterministic 1200×630 H.264/AAC presentation wrapper around the
verified MP3 and the verified Nano Banana 2 cover. It exists only because
GitHub supports native video streaming but not an inline MP3 player; it is not
claimed as another model generation. The square
[Devpost featured image](../../assets/rally-devpost-featured-google-style.png)
is a separate deterministic Rally brand composition in a clean Google-style
visual language. It is not a Nano Banana output or additional model proof. Its
1600×1600 PNG SHA-256 is
`fecd5bab20f2dcfa518b9b043856d9971e1157105a93e07faee14f0908525041`.

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
