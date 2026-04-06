# Test Suite — Vera Accessibility Violations

This folder contains intentionally inaccessible web applications for testing Vera's scanning and auto-fix capabilities.

## Files

### `index.html`
A vanilla HTML page with **11+ intentional accessibility violations**:
- Missing alt text on images
- Low color contrast (text on background)
- Form inputs without labels
- Non-semantic interactive elements (divs as buttons)
- Empty headings
- `aria-hidden` on visible content
- Broken heading hierarchy
- Icon buttons without `aria-label`
- Focusable but hidden elements
- Missing language attributes

### `App.jsx`
A React component with the same violations, suitable for testing Vera with React codebases.

## Running Vera on These Tests

### Test HTML File
```bash
vera scan test/index.html
```

Expected output: **11 violations detected**

### Test React Component
```bash
vera scan test/App.jsx
```

Expected output: **13 violations detected**

## Auto-Fix Validation

After scanning, test the auto-fix pipeline:

```bash
# Preview fixes (dry run)
vera fix test/index.html

# Apply fixes (with confirmation)
vera fix test/index.html --apply
```

## Violations Checklist

**Vera should detect:**
- ✅ Missing `alt` text on `<img>` tags
- ✅ Low color contrast (WCAG AA: 4.5:1 for normal text)
- ✅ Form inputs without `<label>` or `aria-label`
- ✅ Non-semantic interactive elements (e.g., `<div onclick>` instead of `<button>`)
- ✅ Empty headings (`<h1></h1>`)
- ✅ `aria-hidden="true"` on visible content
- ✅ Broken heading hierarchy (h1 → h4 skip)
- ✅ Icon buttons without accessible names
- ✅ Focusable but visually hidden elements
- ✅ Missing language attributes on language-specific content

## Expected Auto-Fixes

Vera should generate code fixes for:
1. **Add alt text** → `<img alt="description" />`
2. **Increase contrast** → CSS color adjustment
3. **Add labels** → `<label for="input-id">`
4. **Semantic elements** → `<button>` instead of `<div onclick>`
5. **Add aria-label** → `<button aria-label="Settings">⚙️</button>`
6. **Remove aria-hidden** → Delete problematic attribute
7. **Fix heading hierarchy** → Change `<h4>` to `<h2>` or `<h3>`
8. **Add language attributes** → `<p lang="es">`

---

## Testing Workflow

1. **Scan for violations:**
   ```bash
   vera scan test/
   ```

2. **View detailed report:**
   ```bash
   vera scan test/ --output report.json
   ```

3. **Preview fixes:**
   ```bash
   vera fix test/ --preview
   ```

4. **Apply fixes:**
   ```bash
   vera fix test/ --apply
   ```

5. **Verify all fixed:**
   ```bash
   vera scan test/
   # Should show 0 violations
   ```

---

## Success Criteria

Vera is working correctly if:
- ✅ Scans detect **all violations** listed above
- ✅ Generated fixes are **syntactically valid** (no broken code)
- ✅ Fixed code passes **Vera's second scan** (0 violations)
- ✅ Dashboard displays violations with correct severity levels
- ✅ Code diffs show accurate before/after changes

---

**Test Early. Test Often. Build Inclusive Apps.** 🚀
