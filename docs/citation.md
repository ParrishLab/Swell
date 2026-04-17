# Citing SDApp

If SDApp contributed to your research, please cite both the methods paper and the archived software release.

## Methods paper

<!-- TODO: replace with final citation once published -->

> Dunford, C. et al. *Manuscript title*. Journal (Year). DOI: `10.xxxx/xxxxxx`

BibTeX:

```bibtex
@article{sdapp_methods,
  author  = {Dunford, Clay and others},
  title   = {Manuscript title},
  journal = {Journal},
  year    = {YYYY},
  doi     = {10.xxxx/xxxxxx}
}
```

## Software release

Each tagged release is archived on Zenodo with its own DOI. Cite the specific version you used.

<!-- TODO: add Zenodo DOI badge and versioned DOI once minted -->

```bibtex
@software{sdapp_software,
  author  = {Dunford, Clay},
  title   = {SDApp: a desktop tool for SD event identification and segmentation},
  year    = {YYYY},
  version = {vX.Y.Z},
  doi     = {10.5281/zenodo.xxxxxxx},
  url     = {https://github.com/ClayDunford/Combined-tool-test}
}
```

## Reproducing manuscript results

<!-- TODO: link example dataset, expected outputs, and the exact release tag used for the figures -->

The manuscript figures were produced with SDApp version `vX.Y.Z` using the default metrics settings documented in [GUI reference](gui/analysis-window.md#metrics-settings).
