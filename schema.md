# Room layout schema — version 1.0

All measurements are inches.

## Coordinate system

The northwest inside corner of a room is `(0, 0)`. `x` increases east and `y`
increases south. Wall feature offsets use the same readable direction on both
opposite walls:

- north and south: west to east
- east and west: north to south

## Furniture catalog

```yaml
version: 1.0
units: inches
objects:
  Sofa84:
    category: sofa
    symbol: sofa
    footprint:
      shape: rectangle
      length: 84
      depth: 34
    render:
      seats: 3
      arms: both
```

`category` describes what the object is. `symbol` selects its visual symbol.
`shape` is explicit in the catalog, although the renderer can infer legacy
rectangle and circle footprints.

Rectangle footprints use `length` and `depth`; circles use `diameter`. Optional
`height` is descriptive and does not affect the floor plan.

## Layout placements

```yaml
version: 1.0
units: inches
placements:
  - id: Sofa
    object: Sofa84
    x: 40
    y: 142
    rotation: 0
```

For rectangles, `(x, y)` is the back-left anchor viewed from behind the object.
Rotation is clockwise and may be any numeric angle: `0` faces north, `90` east,
`180` south, and `270` west. Circle coordinates identify the center.

## Room geometry

```yaml
room:
  id: ExampleRoom
  units: inches
  coordinate_system:
    origin: northwest_inside_corner
    x_direction: east
    y_direction: south
  shape:
    type: rectangle
    width: 180
    depth: 144
  features:
    - id: WestWindow
      type: window
      wall: west
      offset: 44
      width: 60
```

Canonical wall features use `wall`, `offset`, and `width`. Fixed interior
features use numeric `x`, `y`, `width`/`length`, and `depth` fields.

## Annotations

```yaml
annotations:
  - id: HearthCallout
    type: callout
    text: Hearth
    x: 134
    y: 40
    leader_to: {x: 118, y: 19}
  - id: WalkwayWidth
    type: dimension
    from: {x: 48, y: 90}
    to: {x: 152, y: 90}
```

Types are `label`, `area`, `note`, `callout`, and `dimension`. Every annotation
needs a unique `id`. All types except `dimension` need `text`, `x`, and `y`; a
dimension without `text` shows the measured distance. Optional style fields are
`size`, `color`, `bold`, and `rotation`.
