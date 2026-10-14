# Dataset setup

The evaluation uses COCO and Flickr30k images. Download or request the images from their official dataset sites and comply with the dataset terms:

- COCO: https://cocodataset.org/#download — 2014 training and validation images.
- Flickr30k: https://shannon.cs.illinois.edu/DenotationGraph/ — the original image collection.

No dataset images or captions are redistributed here. Ordered filename lists under `configs/` identify the gallery and disjoint calibration inputs; a filename is an image identifier, not image content. Put the original images anywhere under one root per dataset. Image lookup is recursive by exact filename and rejects ambiguous filenames.

The gallery order contains the complete evaluation image prefix, followed by real training distractors. COCO uses a 5,000-image evaluation prefix and up to 50,000 gallery images; Flickr30k uses a 1,000-image evaluation prefix and up to 25,000 gallery images. Each cache also includes spare update images and 512 disjoint training calibration images. Input content duplicates were excluded when the published filename lists were selected. Image queries are the frozen gallery vectors at the published query IDs. No captions or text encoder calls are used.

## Feature cache

For each dataset, provide `gallery.npy`, `calibration.npy`, and `features_complete.json` under `verdi_features/<dataset>/`. Arrays are normalized FP32 image embeddings, 512 dimensions, in the published filename order. `dataset_manifest.json` is also used for image-module experiments. An existing author cache is accepted without modifying it; legacy `texts.npy` and `targets.npy` are not loaded.

The expected image-array SHA-256 hashes and query IDs are packaged in `src/verdi/paper_inputs.json`. Benchmark commands stop on an input hash mismatch. Different encoder environments can produce different arrays; they require a new experiment record and must not be presented as the paper cache.

## Optional image encoding

The extraction script calls an installed image encoder through its public package API; no encoder implementation or pretrained weights are copied into this repository. Install PyTorch/torchvision appropriate for your hardware, the encoder extras, and the encoder package from its official source:

```bash
python -m pip install -e ".[encoder]"
python -m pip install "git+https://github.com/openai/CLIP.git@d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"
python scripts/extract_features.py --dataset coco --images /path/to/coco/images --output /path/to/verdi_features/coco
python scripts/extract_features.py --dataset flickr30k --images /path/to/flickr30k/images --output /path/to/verdi_features/flickr30k
```

The recorded image encoder is CLIP ViT-B/32, FP32 without autocast, batch size 16, with TF32 disabled. The recorded numerical environment uses PyTorch 2.6.0+cu124, torchvision 0.21.0+cu124, Pillow 11.2.1, and an RTX 4060 Ti. Weight SHA-256: `40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af`. Extraction preserves existing cache directories and records whether the resulting arrays match the paper hashes.
