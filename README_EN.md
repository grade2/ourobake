**English** · [中文](README.md)

# Ourobake

Mesh thickness and curvature are baked into an fp32 color attribute that shaders read directly.

| thickness channel | curvature channel |
|---|---|
| ![thickness channel](pic/厚度.jpg) | ![curvature channel](pic/曲率_0.01.jpg) |

Render settings of the images: sample count 256, scale 3 m, differential step scale 0.1, surface offset 0, cone size 0.25. The target model is `xyzrgb_dragon` from the Stanford 3D Scanning Repository.

## The approach

A Blender bake writes its result inside one pass, and Cycles' progressive refine is mutually exclusive with baking ([blender#83344](https://projects.blender.org/blender/blender/issues/83344)), so multi-pass sampling with averaging has no ready-made path inside Blender. Ourobake hands the iteration loop to an add-on: `iterative_baker.py` calls `bpy.ops.object.bake()` repeatedly, while the node group makes the shader read the same color attribute that the bake writes. One bake pass then corresponds to one step of a fixed-point iteration, with the render pipeline serving as the solver step.

## How it works

$P$, $N$ and $T$ come from the Geometry node, and the current attribute value is $C=(R,G,B,A)$. The interface parameters are the sample count $N_s$, the scale $L$, the differential step scale $k$, the surface offset $o$ and the cone size $w$.

A pass begins by reading the iteration count and the averaging weight, where $\varepsilon=10^{-6}$ is a constant inside the node group:

$$n=\frac{B}{\varepsilon},\qquad i=n+1,\qquad f=\frac{1}{n+1},\qquad B'=B+\varepsilon$$

The sample direction lies inside a cone that opens with progress and narrows where curvature is high:

$$s=\frac{i}{N_s},\qquad c=\operatorname{clamp}\left(w\,s\,\operatorname{mix}\left(1,\ \frac{1}{1+LG},\ s^{2}\right),\ 0,\ 1\right)$$

The azimuth follows a golden-ratio sequence, and per-point white noise supplies a different phase origin at each vertex:

$$\theta=\pi\cdot 0.61805\cdot\left(i+2\pi\cdot\mathrm{noise}_{3D}(P)\right)$$

$$\hat e=\operatorname{normalize}\left(\hat B\cos\theta+\hat T\sin\theta\right),\qquad \hat B=\operatorname{normalize}(N\times T)$$

$$d=\operatorname{normalize}\left((1-c)(-N)+c\,\hat e\right)$$

$$t=\mathrm{SelfHit}\left(P-oN,\ d,\ L\right)\cdot\left(\mathrm{HitDistance}+o\right)$$

Curvature comes from the sagitta construction. The probe azimuth is $\varphi=\pi\cdot 0.61805\cdot i$, the two probe points sit at $P_\pm=P\pm h\hat e_c$, and each point fires rays of length $8h$ along $\pm N$ with a miss recorded as 0:

$$h=\operatorname{clamp}\left(R'k,\ 0.01,\ 0.25\right)$$

$$\kappa=\frac{\Sigma d}{h^{2}+\frac{1}{4}(\Sigma d)^{2}},\qquad \Sigma d=d_{1}+d_{2}+d_{3}+d_{4}$$

On a sphere of radius $R$ the sagitta satisfies $s\approx h^{2}/(2R)$; substituting it gives $\kappa\approx 1/R$, which is why the $G$ channel carries units of 1/m. The expression peaks at $1/h$ when $u=2h$ and does not diverge as $h\to 0$.

The pass ends by writing the running mean back into the attribute:

$$R'=(1-f)R+ft,\qquad G'=(1-f)G+f\kappa$$

Output of a pass is the triple $(R',G',B')$, in which the counter has already been incremented by one $\varepsilon$.

## Interface

The node group has 6 inputs and 1 output, and the material chains a *Color Attribute* node, the `群组` node and a *Material Output* node.

| Input | Default | Example | Notes |
|---|---|---|---|
| `颜色属性(FP32)` | — | from the Color Attribute node | the feedback bus; its `layer_name` must match the real attribute name |
| `采样次数` | 64 | 256 | denominator of the cone progress, equal to `Iterations` in the add-on panel |
| `尺度(米)` | 3.0 | 3.0 | thickness ray length, an absolute length |
| `差分步长缩放` | 0.05 | 0.1 | curvature step factor |
| `表面偏移` | 0.0 | 0.0 | inward offset of the ray origin along the normal |
| `采样锥大小` | 0.25 | 0.25 | upper bound of the cone opening |
| `Vector` (output) | — | to `Surface` of the Material Output | result triple, treated as emission once connected to Surface |

## Usage

`thickness&curvature.blend` opens in Blender 5.2 or newer. The add-on `iterative_baker.py` goes into `scripts/addons/` and is enabled from the Render category.

Starting a bake requires a zeroed attribute and equal values for `Iterations` and `采样次数`. The target `xyzrgb_dragon` also needs selection, with the mode set to Object Mode. Both counts already hold 256 in the shipped scene.

```python
import bpy
ca = bpy.data.objects["xyzrgb_dragon"].data.color_attributes["厚度"]
ca.data.foreach_set("color", [0.0] * (len(ca.data) * 4))
```

Render and bake settings match the values stored in the scene:

| Setting | Value |
|---|---|
| Render Engine | Cycles |
| Device | CPU |
| Samples | 1 |
| Adaptive Sampling / Denoise | off |
| Seed / Animated Seed | 0 / off |
| Bake Type | Emit |
| Bake Target | Vertex Colors |
| Selected to Active / Cage | off |

After the run the `厚度` attribute holds $R$ as thickness in meters, $G$ as curvature in 1/m, and $B/10^{-6}$ as the number of completed passes.

## Example

The dragon mesh has 124,943 vertices and 249,881 triangles, scaled to 0.01 on import for a largest dimension of 2.02 m. The source file contains 123 loose vertices belonging to no face, and removing them leaves effective geometry at exactly one hundredth of the source size.

Attribute statistics after 256 passes:

```text
thickness  (m)   mean = 0.172087   min = 0.007495   max = 0.667673
curvature (1/m)  mean = 29.7763    min = 3.37872    max = 92.7339
counter          B    = 2.56001e-4   (256 x 1e-6)
```

A single pass takes about 0.59 s (i9-11900H, CPU, mesh at the size above), so 256 passes take roughly 2.5 minutes. The mean settles within the first few passes, and later passes mainly tighten local estimates.

## Caveats

- Distances are absolute. `尺度(米)` and the curvature step clamps 0.01 and 0.25 are all in meters, so a model needs scaling to metric size first. At the raw 200-unit OBJ size, the 0.01 curvature step is about one twenty-thousandth of the model dimension.
- Blender 5.2 is the version floor, since the shader Raycast node exists from that release. Opening the scene in 5.1 or older loses nodes.
- The attribute type is fp32 `FLOAT_COLOR`, and it must be the active color attribute with a name matching the node's `layer_name`. An 8-bit vertex color cannot hold $10^{-6}$, which stalls the counter at 0.
- Curvature is unsigned, so ridges and valleys read identically. On the `POINT` domain the resolution equals vertex density, independent of UVs and textures.
- Thickness counts rays that hit the object itself; other objects in the scene may nevertheless occlude the measurement.
- Cycles' RNG stays fixed across passes (seed 0, one sample, animated seed off), so diversity comes from the iteration-index-driven azimuth sequence.
- `采样次数` needs a value no smaller than the total pass count; exceeding it saturates the cone expression and distorts thickness readings. The counter resolves up to about $8\times10^{6}$ passes, and the add-on caps the count at 10000.
- Baking overwrites the attribute and leaves no undo record.
- The curvature probe's azimuth contains no jitter.

## Files and license

```text
thickness&curvature.blend   demo scene
iterative_baker.py          companion add-on, named Iterative Baker
pic/                        renders
```

The node group, the demo scene and the add-on are MIT licensed, copyright 2026 [grade2](https://github.com/grade2).

The dragon mesh embedded in `thickness&curvature.blend` comes from the Stanford 3D Scanning Repository and falls outside the MIT license. The terms of that repository require attribution to the Stanford Computer Graphics Laboratory and restrict use to research and free redistribution, with commercial use excluded. Removing the mesh leaves the remainder freely usable under MIT.
