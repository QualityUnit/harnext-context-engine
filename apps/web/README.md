# apps/web — Dashboard

Next.js 15 (App Router) + React 19 + Tailwind 4 + Cytoscape.js. The semantic-graph view goes here.

See [`docs/architecture/dashboard.md`](../../docs/architecture/dashboard.md) for the plan — including which parts of FalkorDB Browser we borrow vs adapt (§5) and the wire shape `GET /api/v1/graph` returns (§6).

## Run (dev)

```bash
make web    # from repo root → http://localhost:3000
```

Or directly:

```bash
pnpm --filter @meaninggrid/web dev
```

## Layout (planned per dashboard.md §7)

```
app/
├── layout.tsx
├── page.tsx          — landing (currently a placeholder)
├── globals.css
└── graph/            — the centerpiece (to be built)
    ├── page.tsx
    ├── GraphView.tsx
    ├── TableView.tsx
    ├── EntityPanel.tsx
    ├── Toolbar.tsx
    ├── layouts.ts
    ├── styles.ts
    └── types.ts
```
