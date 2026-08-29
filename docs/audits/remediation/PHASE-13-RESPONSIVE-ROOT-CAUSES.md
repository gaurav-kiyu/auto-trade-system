# OPB SUPER-PLATFORM — PHASE 13 RESPONSIVE ROOT CAUSE ANALYSIS (RCA)

**Document**: `PHASE-13-RESPONSIVE-ROOT-CAUSES.md`  
**Standard**: OPB-RCA-GOVERNANCE-001  
**Classification**: High-Priority UI/UX Defect Remediation  

---

## 1. Defect 1: Navigation Menu Title Character-by-Character Vertical Wrapping

### 1.1 Observed Behavior
When opening the global slide-over drawer on mobile devices (<1024px), the title rendered vertically:
```text
📋
N
A
V
I
G
A
T
I
O
N
 
M
E
N
U
```

### 1.2 Root Cause Analysis
1. In `static/opb_design_system.css` (lines 224–227), broad text boundaries were declared:
   ```css
   .opb-text-bound, .config-desc-box, .opb-card, p, span, div {
       overflow-wrap: anywhere;
       word-break: break-word;
   }
   ```
2. In `templates/enterprise/_nav.html` (lines 496–501), `.drawer-header` is a flex container with `justify-content: space-between`.
3. Because the child `<span>` element lacked `flex-shrink: 0` and `white-space: nowrap !important;`, the flex layout algorithm permitted the container to collapse the span's width to just `19.5px`.
4. Under `overflow-wrap: anywhere; word-break: break-word;`, words broke at every individual glyph, causing the title to render vertically across 265px of vertical height.

### 1.3 Remediation
Enforced absolute text boundary protection on navigation components in `static/opb_design_system.css`:
```css
.drawer-header {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    min-height: 48px !important;
    max-height: 52px !important;
    padding: 0.65rem 1rem !important;
    flex-shrink: 0 !important;
    white-space: nowrap !important;
}

.drawer-header span {
    white-space: nowrap !important;
    word-break: keep-all !important;
    overflow-wrap: normal !important;
    flex-shrink: 0 !important;
    font-size: 0.85rem !important;
    font-weight: 800 !important;
    letter-spacing: 0.05em !important;
}
```

---

## 2. Defect 2: Drawer Close "X" Button Distortion

### 2.1 Observed Behavior
The close button expanded into a wide 267px rectangular container and was pushed downward towards the middle of the screen.

### 2.2 Root Cause Analysis
The close trigger used `<label class="mobile-hamburger-btn">`. The global `.mobile-hamburger-btn` class contained flex-grow rules and sizing intended for the top navbar hamburger button, which distorted when placed inside the space-between drawer header alongside a collapsed span.

### 2.3 Remediation
Created a dedicated `.drawer-close-btn` rule with rigid dimensions (`36px x 36px`), centered SVG alignment, and `flex-shrink: 0; flex-grow: 0;`.

---

## 3. Defect 3: Excessive Backdrop Blur & Background Darkening

### 3.1 Observed Behavior
The backdrop overlay darkened the entire background to near pitch-black (`rgba(0,0,0,0.75)`) and applied a heavy `blur(8px)` effect, making the underlying context completely illegible.

### 3.2 Root Cause Analysis
In `_nav.html`, the backdrop active state was configured with `background: rgba(0,0,0,0.75)` and `backdrop-filter: blur(8px)`.

### 3.3 Remediation
Tuned backdrop overlay to `rgba(0,0,0,0.5)` with `backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);`.

---

## 4. Defect 4: Horizontal Viewport Blowouts on Mobile

### 4.1 Observed Behavior
Multiple dashboard screens produced horizontal scrollbars on viewports <=430px (`scrollWidth > innerWidth`).

### 4.2 Root Cause Analysis
1. `.ambient-glow`: Fixed width/height of `500px` without viewport constraints expanded `scrollWidth` to 445px–500px on narrow devices.
2. `.opb-cockpit-grid`: CSS Grid children had default `min-width: auto;` causing chart containers and tab bars to expand the grid container width to 609px.
3. `.opb-tab-bar`: Declared as `inline-flex` without `max-width: 100%` or horizontal overflow scrolling.

### 4.3 Remediation
1. Bound ambient glow: `.ambient-glow { max-width: 90vw !important; max-height: 90vw !important; }`.
2. Added `.opb-cockpit-grid > div { min-width: 0; max-width: 100%; }`.
3. Set `.opb-tab-bar { display: flex !important; max-width: 100% !important; overflow-x: auto !important; }`.
4. Applied global `html, body { max-width: 100vw !important; overflow-x: hidden !important; }`.
