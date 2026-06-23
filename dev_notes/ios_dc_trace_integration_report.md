
# Integrating a DC Trace Viewer into an Existing IOS Analysis Tool

## Purpose

This report describes what your **existing IOS analysis framework** would need in order to load, synchronize, and display a **DC electrophysiology trace** alongside IOS footage, without redesigning the app from scratch.

The emphasis is on **integration requirements**, not a greenfield implementation. The recommended approach is to add a small, format-aware **trace ingestion and synchronization layer** that plugs into your current viewer and analysis pipeline.

---

## Executive summary

The core problem is not plotting a second panel. It is establishing a reliable mapping between:

- **video time** (frame index, frame timestamps, FPS, dropped/trimmed frames), and
- **ephys time** (sample index, sample rate, sweep structure, trigger timing, channel metadata).

For your tool, the minimum viable integration is:

1. Add a **trace adapter interface** that converts external ephys files into one normalized in-memory representation.
2. Add a **time alignment object** that maps video time to trace time.
3. Add a **linked trace viewer panel** with shared cursor, zoom, and event markers.
4. Start with **WaveSurfer `.h5`** support first, because it is likely the highest-yield format for your context.
5. Keep the design extensible so you can later add **Intan**, **NWB**, and possibly **ABF** without changing the rest of the app.

---

## What should be added to the existing framework

### 1) A normalized trace data model

Your app should not let the rest of the codebase depend directly on WaveSurfer, Intan, or NWB file structure. Instead, add one internal representation such as:

```python
@dataclass
class TraceRecord:
    source_type: str                  # "wavesurfer", "intan", "nwb", etc.
    channel_names: list[str]
    units: list[str]                  # e.g. ["mV"], ["uV"], ["V"]
    sample_rate_hz: float | None
    timestamps_s: np.ndarray | None   # preferred if available
    signals: np.ndarray               # shape: [n_samples, n_channels]
    segments: list[tuple[int, int]]   # optional for sweep/gap structure
    start_time_s: float | None
    metadata: dict
```

This model is the integration boundary. Every file-specific loader should return this object.

### 2) A trace source / adapter interface

Add a plugin-style reader interface that your existing project can call:

```python
class TraceAdapter(Protocol):
    def sniff(self, path: Path) -> bool: ...
    def load_metadata(self, path: Path) -> dict: ...
    def load_trace(self, path: Path, channel_selection=None) -> TraceRecord: ...
```

Recommended first adapters:

- `WaveSurferH5Adapter`
- `IntanAdapter` (later)
- `NWBAdapter` (later)
- `ABFAdapter` (optional later)

This keeps all file-specific logic out of the IOS viewer and analysis code.

### 3) A time alignment layer

Add a single alignment object to describe how the trace lines up with the IOS footage:

```python
@dataclass
class TimeAlignment:
    mode: Literal[
        "shared_start_time",
        "manual_offset",
        "trigger_based",
        "explicit_timestamps",
        "per_sweep_mapping"
    ]
    video_t0_s: float
    trace_t0_s: float
    offset_s: float
    drift_ppm: float | None = None
    notes: str = ""
```

Your app should never assume that frame 0 equals sample 0 unless that has been explicitly established.

### 4) A linked trace viewer panel

The viewer integration can stay lightweight if it supports the following:

- docked or split-pane trace panel under or beside the IOS view
- shared playhead / cursor
- click trace -> jump video frame
- move video frame -> move trace cursor
- zoom/pan in time on both views
- optional channel selector
- markers for SD onset, nadir, recovery, stimulation, artifacts, and annotations
- baseline window overlays if your existing app already computes baseline-relative metrics

---

## Recommended integration architecture

A low-friction architecture would look like this:

```text
Existing IOS stack
    ├── Video loader / stack model
    ├── Analysis state
    ├── ROI and annotation tools
    └── Viewer
           │
           ├── New: Trace adapter manager
           ├── New: TraceRecord cache
           ├── New: TimeAlignment object
           └── New: Linked trace panel
```

### Key principle

Only **three** new concepts need to enter the existing framework:

- `TraceRecord`
- `TimeAlignment`
- `TracePanelController`

Everything else can remain format-specific and isolated in adapters.

---

## Phase 1 target: WaveSurfer `.h5`

## Why WaveSurfer first

WaveSurfer stores acquisition data in HDF5, and the manual shows sweep-organized analog data such as `sweep_0001/analogScans`. WaveSurfer also warns that analog samples are stored as signed 16-bit counts and must be converted using calibration coefficients from `/header/Acquisition/AnalogScalingCoefficients`; simply applying a linear scale can produce values that are systematically off by 5-10%. The manual also describes sweep-based acquisition and a `dataAvailable()` callback that emits newly acquired chunks, typically around 100 ms at the frontend. This makes WaveSurfer a good first target both for offline import and for possible future live integration.

### What the WaveSurfer adapter must do

Your adapter should:

1. Open the HDF5 file safely and inspect group/dataset structure.
2. Read sweep-organized analog data.
3. Read the relevant header metadata:
   - sample rate
   - channel names / device mapping
   - unit information if available
   - sweep duration / sweep count
   - scaling coefficients
4. Convert stored counts to engineering units using the WaveSurfer scaling rules.
5. Return either:
   - one concatenated `TraceRecord` with `segments`, or
   - one `TraceRecord` per sweep, depending on how your existing app organizes IOS sessions.

### Recommended representation for WaveSurfer sessions

For an IOS viewer, the cleanest approach is usually:

- **concatenate sweeps into one logical trace**
- store sweep boundaries in `segments`
- preserve any inter-sweep gaps explicitly

That gives you one continuous UI while retaining enough structure to support sweep-aware analysis.

### Validation requirement

Before trusting the loader, compare your custom parse against WaveSurfer's own loader on representative files. WaveSurfer explicitly recommends ensuring custom code gives answers identical to `ws.loadDataFile()` on representative data files.

---

## Future formats worth leaving room for

### Intan (`.rhd`, `.rhs`, or split `.dat` sets)

Intan files carry sample indices that are converted to seconds by dividing by the amplifier sampling rate. The published Intan data format notes also document raw voltage conversions and explain that some auxiliary channels are sampled at lower rates but repeated so they align with the timestamp vector. This means Intan support fits well into the same normalized `TraceRecord` model.

### NWB (`.nwb`)

NWB already formalizes time series storage. Its `TimeSeries` model stores time-varying data as a data array plus either:
- an explicit `timestamps` array, or
- `starting_time` and `rate`.

That is very close to the normalized model recommended here, so NWB is an excellent long-term interchange/export target.

### ABF (`.abf`)

ABF is still useful to keep in mind for compatibility with patch-clamp or legacy workflows. It does not need to be part of your first milestone unless your user base expects it.

---

## Time synchronization requirements

This is the most important part of the integration.

### What the app must represent

Your framework needs a consistent way to answer:

- What trace sample corresponds to the currently displayed video frame?
- What video frame corresponds to a click at trace time `t`?
- Are both streams truly synchronized, or only approximately offset-aligned?
- Is synchronization global for the whole recording, or does it vary by sweep/run?

### Minimum supported alignment modes

#### A. Fixed offset alignment
Use when both recordings start independently but with a known constant offset.

Store:
- video start time
- trace start time
- offset in seconds

#### B. Trigger-based alignment
Use when both systems share a trigger or can be aligned via a stimulus pulse / digital edge / known event.

Store:
- trigger event time in video coordinates
- trigger event time in trace coordinates
- optional confidence / source of alignment

#### C. Explicit timestamp alignment
Use when either stream provides timestamps rather than only uniform sampling assumptions.

Preferred whenever available.

#### D. Per-sweep alignment
Use when each IOS clip or acquisition segment corresponds to a specific ephys sweep.

Store:
- video segment -> sweep mapping
- per-segment offset
- optional dropped/ignored segments

### Drift handling

For long recordings, the app should have a place to represent timing drift even if you do not implement active correction at first. A small slope term or drift estimate field is enough initially.

---

## What needs to change in the UI

Because your analysis tool already exists, the UI work should focus on one new coordinated panel rather than a redesign.

### Required interactions

1. **Shared time cursor**
   - vertical cursor line on trace
   - highlighted current frame in the video timeline

2. **Bidirectional navigation**
   - clicking the trace jumps the IOS viewer to the corresponding frame
   - scrubbing frames updates the trace cursor

3. **Viewport-aware plotting**
   - do not render the full raw trace at maximum resolution if the user is zoomed out
   - decimate or min/max downsample for display

4. **Annotation linkage**
   - an event created in the IOS viewer can appear as a marker on the trace
   - an event created from the trace can appear on the frame timeline

5. **Channel selection**
   - at minimum, choose one displayed channel
   - optionally allow overlays of multiple channels if your rigs record more than one analog signal

### Helpful but optional additions

- baseline shading
- SD threshold lines
- derived trace overlays (smoothed, baseline-subtracted, detrended)
- artifact spans / excluded regions
- sweep boundary markers

---

## Data flow inside the existing app

A practical sequence is:

1. User opens or already has an IOS session loaded.
2. User attaches an ephys file.
3. Adapter reads metadata first, not full data.
4. App shows:
   - channels
   - sample rate
   - sweep structure
   - trace duration
5. User chooses channel and alignment mode.
6. App loads selected trace data into `TraceRecord`.
7. App creates `TimeAlignment`.
8. Linked viewer becomes active.
9. Existing analysis modules can query trace values through a small accessor API.

### Accessor methods worth adding

```python
def get_trace_time_for_frame(frame_idx: int) -> float: ...
def get_frame_for_trace_time(t_s: float) -> int: ...
def get_trace_window(t0_s: float, t1_s: float, channel_idx: int) -> np.ndarray: ...
def get_trace_value_at_frame(frame_idx: int, channel_idx: int) -> float: ...
```

These accessors let the rest of your app stay agnostic about file format and alignment details.

---

## Performance requirements

Even a single-channel DC trace can be long enough to cause UI problems if handled naively.

### Recommended performance strategy

- lazy-load metadata first
- memory-map or chunk-load large arrays when possible
- cache one or more display-resolution summaries of the trace
- when zoomed out, render a decimated or min/max envelope view
- when zoomed in, fetch raw samples for the current time window only

This is especially important if you later add Intan or multi-channel support.

### Why HDF5 is helpful here

HDF5 is organized around groups and datasets, and tools such as `h5py` let you access datasets in an array-like way without forcing you to eagerly load the entire file. That makes WaveSurfer and NWB good fits for lazy trace access.

---

## Analysis integration points

Once the trace is accessible through the normalized model, your existing IOS analysis code can add trace-aware features without depending on file format details.

Examples:

- show DC value at current frame
- compute DC baseline over the same interval used for IOS baseline frames
- place SD onset / nadir / recovery markers on both the image and trace timelines
- calculate lag between IOS-derived event time and DC-derived event time
- export synchronized figures or reports

### Best practice

Keep these analysis features downstream of the normalized trace model. Do not let analysis code reach back into raw HDF5 groups or vendor-specific headers.

---

## Edge cases the framework must handle

1. **Trace present, but no exact alignment available**
   - permit manual offset mode
   - visually flag alignment as approximate

2. **Multiple sweeps or segmented acquisition**
   - do not silently concatenate without preserving boundaries

3. **Different durations**
   - trace longer than video
   - video longer than trace
   - missing sections

4. **Dropped frames / trimmed footage**
   - frame index alone may not be enough; timestamps may be needed

5. **Different units or scaling conventions**
   - mV, V, uV, ADC counts
   - scaling must be explicit and recorded in metadata

6. **Multiple candidate channels**
   - board ADC, amplifier, auxiliary, stimulus monitor, etc.

7. **Future multi-file sessions**
   - one IOS session may eventually map to multiple trace files or sweeps

---

## Testing and validation plan

### Essential tests

#### Loader tests
- can identify supported file type
- can read metadata without full load
- can load trace samples and channel names
- scaling output is correct

#### Synchronization tests
- fixed offset mapping is reversible
- frame -> time -> frame round-trip is stable
- per-sweep mapping uses the correct segment
- out-of-range accesses are handled safely

#### Viewer tests
- clicking trace updates frame
- frame stepping updates trace cursor
- markers remain consistent under zoom
- decimation does not change cursor mapping

### Gold-standard validation for WaveSurfer

Use a small set of representative `.h5` files and compare your parsed/scaled output against WaveSurfer's own loader output.

---

## Recommended implementation order

### Milestone 1: internal interfaces
Add:
- `TraceRecord`
- `TraceAdapter`
- `TimeAlignment`
- trace accessor methods

### Milestone 2: WaveSurfer offline support
Add:
- metadata parsing
- analog trace loading
- proper scaling
- channel selection
- sweep boundary handling

### Milestone 3: linked UI
Add:
- docked trace panel
- shared cursor
- click-to-jump
- frame-to-trace linkage

### Milestone 4: annotation integration
Add:
- event markers
- baseline windows
- export-ready synchronized views

### Milestone 5: future adapters
Consider:
- Intan via direct parsing or Neo
- NWB via PyNWB
- ABF via pyABF if needed

---

## Suggested Python libraries

These are integration helpers, not framework requirements:

- **h5py** for WaveSurfer and generic HDF5 access
- **PyNWB** for NWB support
- **Neo** if you want a broader ephys file-format abstraction layer later
- **pyABF** if ABF support ever becomes worthwhile

For a first pass, `h5py` alone is likely enough if you are targeting WaveSurfer first.

---

## Recommendation

For your current tool, the most efficient path is:

1. implement a **WaveSurfer-only adapter first**
2. normalize the result into one internal `TraceRecord`
3. add a single **time alignment object**
4. expose a **linked trace panel**
5. keep everything else in the existing framework unchanged

That approach treats the root issue—synchronization and clean integration boundaries—rather than just adding another visualization widget.

---

## Practical bottom line

To connect DC traces into your existing IOS analysis tool, you do **not** need a new architecture. You need:

- one format adapter layer
- one normalized trace model
- one time-alignment model
- one linked viewer panel
- a small set of trace accessors used by the rest of the app

If you do that cleanly, WaveSurfer can be added now, and other ephys formats can follow later without forcing a rewrite.

---

## References

1. WaveSurfer manual: sweep-based acquisition, analog data organization, scaling coefficients, and `dataAvailable()` behavior.  
   https://wavesurfer.janelia.org/manual-0.945/index.html

2. WaveSurfer GitHub repository / project overview.  
   https://github.com/JaneliaSciComp/Wavesurfer

3. h5py documentation: HDF5 groups and datasets as Python objects.  
   https://docs.h5py.org/

4. NWB overview: `TimeSeries` stores a data array plus either timestamps or starting time + rate.  
   https://github.com/NeurodataWithoutBorders/nwb-overview/

5. PyNWB documentation.  
   https://pynwb.readthedocs.io/

6. Intan RHD data format application note: timestamps, sample rate conversion, voltage conversion, split-file layout.  
   https://intantech.com/files/Intan_RHD2000_data_file_formats.pdf

7. Neo RawIO documentation and implemented format list.  
   https://neo.readthedocs.io/

8. pyABF documentation.  
   https://swharden.com/pyabf/
