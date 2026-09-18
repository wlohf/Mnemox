# UI component sources

`ClickSpark.tsx` adapts the TypeScript/CSS ClickSpark component fetched from
[React Bits](https://reactbits.dev/r/ClickSpark-TS-CSS.json) on 2026-09-11.
Copyright (c) 2026 David Haz. The complete MIT + Commons Clause license is
preserved in [licenses/react-bits-LICENSE.md](licenses/react-bits-LICENSE.md).

The adaptation limits sparks to marked controls, skips disabled/loading controls
and keyboard clicks, respects live reduced-motion preferences, supports HiDPI,
and stops the animation loop when idle or hidden. The canvas is decorative and
never intercepts input.

`ActionButton` retains Ant Design's button implementation and semantics.
`FoldPanel` is a project-owned accessible disclosure with reversible CSS grid
motion. GSAP and its React hook coordinate the homepage entrance and cleanup.
