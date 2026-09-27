# Fiction shelf

Staging content for the `/fiction/` section of addocdeliverables.ca.

| File | Route |
|---|---|
| `index.mdx` | `/fiction/` |
| `no-longer-living.mdx` | `/fiction/no-longer-living/` |

## Wiring rules

- Add `/fiction/` to the scoped pages: `/`, `/work/`, `/work/project-slug/`, `/about/`, `/resume/`, `/contact/`, `/fiction/`.
- Link it from the **footer only**. Don't add it to the main navigation.
- Don't link to it from `/work/` or `/resume/`, and don't cross-link to Adamic Theory pages.
- Indexing is allowed (no `noindex`).
- Each story's Robert Shiraz bio is written new for that story. Never reuse one.
- Every story opens with a one-line content note.

## Content-note styling (Night-Gold)

```html
<aside class="border-l-4 border-[#FBBF24] bg-[#172A46] text-[#CCD6F6] px-4 py-3 rounded">
```

Contrast: light grey on deep blue is 10.0:1. Gold on deep blue is 8.6:1, and gold on midnight blue is 10.5:1. All pass WCAG AA.
