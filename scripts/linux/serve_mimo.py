#!/usr/bin/env python3
"""Expose ExLlamaV3's cache quantization in the pinned MiMo server entrypoint."""
import argparse
import sys
from localai import paths

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--cache-bits', type=int, choices=[8, 16], default=8)
    options, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]
    source = paths()['apps'] / 'kyojin'
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(source / 'tools/mimo'))
    from tools.mimo import serve
    original_parse = argparse.ArgumentParser.parse_args

    def model_options(parser, *positional, **keywords):
        args = original_parse(parser, *positional, **keywords)
        # The server imports ExLlama only after setting its lossless-kernel
        # defaults. Intercept its internal model parser, preserving that order.
        if hasattr(args, 'cache_quant') and hasattr(args, 'cache_size'):
            if options.cache_bits == 8:
                args.cache_quant = '8'
            print(f'LocalAi MiMo adapter: KV cache {options.cache_bits} bits', flush=True)
            argparse.ArgumentParser.parse_args = original_parse
        return args

    argparse.ArgumentParser.parse_args = model_options
    serve.main()

if __name__ == '__main__': main()
