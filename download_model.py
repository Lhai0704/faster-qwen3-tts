from huggingface_hub import snapshot_download
from pathlib import Path
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--model', choices=['0.6B', '1.7B'], default='0.6B')
args = parser.parse_args()
revisions = {'0.6B': '5d83992436eae1d760afd27aff78a71d676296fc', '1.7B': 'fd4b254389122332181a7c3db7f27e918eec64e3'}
path = snapshot_download(f'Qwen/Qwen3-TTS-12Hz-{args.model}-Base', revision=revisions[args.model], max_workers=4)
filename = 'model-path.txt' if args.model == '0.6B' else 'model-path-1.7B.txt'
Path(__file__).with_name(filename).write_text(path, encoding='utf-8')
print(path, flush=True)
