# Glossary

This glossary defines common terms used in Swell's intrinsic optical signal
imaging and spreading depolarization analysis workflows.

## Intrinsic optical signal imaging

Intrinsic optical signal imaging is an optical imaging technique that measures
activity-related changes in tissue reflectance or intensity over time. Swell
uses image stacks from these recordings to review events, segment wavefronts,
and quantify event-level dynamics.

## Spreading depolarization

Spreading depolarization is a propagating wave of neuronal and glial
depolarization. In optical imaging data, it can appear as a time-varying
intensity change that moves across tissue.

## Cortical spreading depression

Cortical spreading depression is a form of spreading depolarization observed in
cortex. Swell uses the broader SD workflow to mark, segment, and quantify these
events in image stacks.

## SD wavefront

The SD wavefront is the moving boundary of the spreading depolarization or
spreading depression event. Swell's segmentation tools and SAM-2 propagation
workflow help trace this boundary across frames.

## Propagation speed

Propagation speed estimates how quickly the segmented SD wavefront moves over
time. Swell reports this metric from frame-to-frame mask changes when frame
rate and physical scale are available.

## Recruited area

Recruited area is the segmented tissue area involved in the event. Swell exports
area metrics in pixels and calibrated physical units when scale information is
configured.

## Region of interest

A region of interest (ROI) limits analysis to a selected tissue area. Swell can
use ROI settings for area, relative area, speed, and intensity calculations.

## DC trace

A DC trace is an electrophysiological recording that can be aligned with the
image-stack timeline. Swell can attach DC traces to support event review and
export.

## SAM-2 propagation

SAM-2 propagation uses the Segment Anything Model 2 runtime to extend prompts,
brush edits, and mask anchors across an event's frame range. Swell supports
manual review and correction after propagation.
