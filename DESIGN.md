# Logistics Dispatch Workspace

## Direction

The interface behaves like a contemporary railway signal-box diagram: a finite network, explicit occupancy, and one valid movement at a time. The visual anchor is Swiss—neutral white surfaces, black typography, strict hairline grids, and Yves Klein blue as the sole signal colour.

## First viewport

The signed-in desktop view opens with a compact application masthead and a four-cell run strip. The dispatch board immediately follows: transfer lifecycle tracks occupy the wide column while request transport and fleet capacity form a narrow operating rail. Diagnostics, jobs, controls, audit, commands, and custody history remain below or inside deliberate disclosure sections.

## Typography and colour

- Use Helvetica Neue, Helvetica, Arial, or system sans throughout.
- Use tabular numerals for simulation time, quantities, and identifiers.
- Surfaces are `#ffffff` and `#f7f7f8`; ink is `#111111`.
- Yves Klein blue `#002fa7` is the only chromatic accent.
- State remains understandable through text, shape, border weight, and position without colour.

## Structure and controls

- Use square corners and one-pixel rules; no shadows, gradients, grain, or ornamental texture.
- Keep standard action wording from the product.
- Every primary control is at least 44 pixels high and has a visible focus ring.
- Tables remain available for dense reference data; active transfers become track cards with a seven-stage lifecycle.
- The layout collapses to one column below 900 pixels, with lifecycle tracks horizontally scrollable rather than compressed into illegibility.

## Signature interaction

Each transfer renders as a block track: Requested, Assigned, Loaded, Departed, Arrived, Unloaded, Received. Completed blocks are solid, the current block is outlined in blue, and future blocks remain neutral. The contextual action sits on the same card, connecting system state to the next valid movement.

## Motion

Hover and focus changes use short 120–160 ms transitions. No looping animation. Reduced-motion preferences remove transitions.

## Content discipline

Use only fields already returned by the Logistics API. Do not invent operators, transfer data, performance metrics, customer claims, or decorative labels.
