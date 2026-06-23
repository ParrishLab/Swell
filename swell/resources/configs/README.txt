Place SAM2 config files here using this structure:

configs/
  sam2/
    sam2_hiera_b+.yaml
    sam2_hiera_s.yaml
    sam2_hiera_l.yaml
    sam2_hiera_t.yaml
  sam2.1/
    sam2.1_hiera_b+.yaml
    sam2.1_hiera_s.yaml
    sam2.1_hiera_l.yaml
    sam2.1_hiera_t.yaml

The app will prefer these local configs if present.
