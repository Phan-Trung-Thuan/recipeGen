"""
Minimal (byte-level) Byte Pair Encoding tokenizer.

Algorithmically follows along the GPT tokenizer:
https://github.com/openai/gpt-2/blob/master/src/encoder.py

But:
- Does not handle the regular expression splitting pattern.
- Does not handle any special tokens.
"""

from .base import Tokenizer, get_stats, merge
import numpy
import torch

class BasicTokenizer(Tokenizer):

    def __init__(self):
        super().__init__()

    def train(self, text, vocab_size, verbose=False):
        assert vocab_size >= 256
        num_merges = vocab_size - 256

        # input text preprocessing
        text_bytes = text.encode("utf-8") # raw bytes
        ids = list(text_bytes) # list of integers in range 0..255

        # iteratively merge the most common pairs to create new tokens
        merges = {} # (int, int) -> int
        vocab = {idx: bytes([idx]) for idx in range(256)} # int -> bytes
        for i in range(num_merges):
            print(i, '/', num_merges)
            # count up the number of times every consecutive pair appears
            stats = get_stats(ids)
            # find the pair with the highest count
            pair = max(stats, key=stats.get)
            # mint a new token: assign it the next available id
            idx = 256 + i
            # replace all occurrences of pair in ids with idx
            ids = merge(ids, pair, idx)
            # save the merge
            merges[pair] = idx
            vocab[idx] = vocab[pair[0]] + vocab[pair[1]]
            # prints
            if verbose:
                print(f"merge {i+1}/{num_merges}: {pair} -> {idx} ({vocab[idx]}) had {stats[pair]} occurrences")

        # save class variables
        self.merges = merges # used in encode()
        self.vocab = vocab   # used in decode()

    def train_vectorized(self, text, vocab_size, verbose=False):
        assert vocab_size >= 256
        num_merges = vocab_size - 256

        # input text preprocessing
        text_bytes = text.encode("utf-8") # raw bytes
        ids = list(text_bytes) # list of integers in range 0..255

        # iteratively merge the most common pairs to create new tokens
        merges = {} # (int, int) -> int
        vocab = {idx: bytes([idx]) for idx in range(256)} # int -> bytes

        ids = numpy.array(ids)
        for i in range(num_merges):            
            print(i, '/', num_merges)
            
            pairs = numpy.stack((ids[:-1], ids[1:]), axis=1)
            unique, counts = numpy.unique(pairs, return_counts=True, axis=0)
            pair_index = numpy.argmax(counts)
            pair = unique[pair_index]
            count = counts[pair_index]

            # mint a new token: assign it the next available id
            idx = 256 + i

            mask = numpy.all(pairs == pair, axis=1)
            mask = numpy.append(mask, False)
            ids[mask] = idx
            ids = ids[~numpy.roll(mask, 1)]

            # save the merge
            merges[tuple(pair)] = idx
            vocab[idx] = vocab[pair[0]] + vocab[pair[1]]
            # prints
            if verbose:
                print(f"merge {i+1}/{num_merges}: {pair} -> {idx} ({vocab[idx]}) had {count} occurrences")

        # save class variables
        self.merges = merges # used in encode()
        self.vocab = vocab   # used in decode()

    def train_gpu(self, text: str, vocab_size: int, verbose=False):
        assert vocab_size >= 256
        num_merges = vocab_size - 256

        # input text preprocessing
        text_bytes = text.encode("utf-8") # raw bytes
        ids = list(text_bytes) # list of integers in range 0..255

        ids = torch.tensor(ids, dtype=torch.int64).cuda()
        merge_pairs = torch.zeros((num_merges, 2), dtype=torch.int64).cuda()

        for i in range(num_merges):
            print(i, '/', num_merges)
            
            pairs = torch.stack((ids[:-1], ids[1:]), dim=1)
            unique, counts = torch.unique(pairs, return_counts=True, dim=0)
            pair_index = torch.argmax(counts)
            pair = unique[pair_index]
            count = counts[pair_index]

            mask = torch.all(pairs == pair, dim=1)
            mask = torch.cat((mask, torch.tensor([False]).cuda()))
            ids[mask] = i + 256
            ids = ids[~torch.roll(mask, 1, 0)]

            merge_pairs[i] = pair

        self.merges = {
            tuple(pair.tolist()): j + 256
            for j, pair in enumerate(merge_pairs)
        }

        vocab = {idx: bytes([idx]) for idx in range(256)} # int -> bytes
        for i in range(num_merges):
            pair = merge_pairs[i]
            idx = 256 + i
            pair_tuple = tuple(pair.tolist())
            vocab[idx] = vocab[pair_tuple[0]] + vocab[pair_tuple[1]]
            if verbose:
                print(f"merge {i+1}/{num_merges}: {pair_tuple} -> {idx} ({vocab[idx]}) had {count} occurrences")
        self.vocab = vocab

    def decode(self, ids):
        # given ids (list of integers), return Python string
        text_bytes = b"".join(self.vocab[idx] for idx in ids)
        text = text_bytes.decode("utf-8", errors="replace")
        return text

    def encode(self, text):
        # given a string text, return the token ids
        text_bytes = text.encode("utf-8") # raw bytes
        ids = list(text_bytes) # list of integers in range 0..255
        while len(ids) >= 2:
            # find the pair with the lowest merge index
            stats = get_stats(ids)
            pair = min(stats, key=lambda p: self.merges.get(p, float("inf")))
            # subtle: if there are no more merges available, the key will
            # result in an inf for every single pair, and the min will be
            # just the first pair in the list, arbitrarily
            # we can detect this terminating case by a membership check
            if pair not in self.merges:
                break # nothing else can be merged anymore
            # otherwise let's merge the best pair (lowest merge index)
            idx = self.merges[pair]
            ids = merge(ids, pair, idx)
        return ids
