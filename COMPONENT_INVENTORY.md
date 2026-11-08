# Component inventory

The Step 1 brief asked for a React front end with shadcn/ui and these components. That version was **built and
verified** (Vite 8, React 19, TypeScript 7, Tailwind 4, React Router 8, motion 14), then **set aside on Nov 7 at the
team's request** in favour of the hand-built UI based on the team's reference example. It is not in the deployed app.

| Requested component | What it actually is | Status in the React build | Status in the shipped app |
|---|---|---|---|
| `@skiper-ui/skiper40` | Six CSS-only animated text links (underline sweeps, arrow nudge, blend-mode fill). Free tier, attribution required. | Installed from the Skiper UI registry JSON; adapted from Next.js `Link` to React Router | Not used |
| `@magicui-pro/header-1` | Magic UI **Pro** header block | **Blocked:** needs a paid Magic UI Pro license key (not supplied, not purchased). A labeled substitute header was built to the reference site's measurements | Not used |
| `@magicui/animated-list` | Items appear one by one | Installed (registry JSON from Magic UI's GitHub) | Not used |
| `@magicui/dock` | macOS-style dock with magnification | Installed | Not used |
| `@magicui/progressive-blur` | Layered backdrop blur at an edge | Installed | Not used |
| `@magicui/border-beam` | Light travelling around a border | Installed | Not used |
| `@magicui/aurora-text` | Animated gradient text | Installed | Not used |
| `@magicui/animated-shiny-text` | Shimmer across text | Installed | Not used |
| `@magicui/number-ticker` | Spring-animated count | Installed | Not used |
| `@magicui/shimmer-button` | Button with a travelling shimmer | Installed | Not used |
| `@magicui/retro-grid` | Perspective grid background (WebGL with CSS fallback) | Installed | Not used |

**Why components were installed from registry JSON instead of the shadcn CLI:** the build environment could not reach
`ui.shadcn.com` (the CLI fetches colors and style files from there), so the CLI failed. The same registry items were
fetched from Magic UI's public GitHub repository and the Skiper UI registry, and their files were written exactly
as the CLI would, with the same `@/lib/utils` import rewrite.

**Shipped app:** `web/static/` (vanilla HTML/CSS/JS, no third-party JavaScript). Its equivalents of the effects above
are hand-written: count-up stats, score rings, reveals, command menu, drawer, SVG charts.
