"""Command line: radiomp3 decode / radiomp3 testsignal."""

import argparse
import os
import sys

from . import __version__
from .encoder import damage, file_rows, interleave, packets, stream_rows
from .sink import Sink
from .superblock import SuperblockDecoder
from .teletext import PageAssembler, read_t42


def cmd_decode(args):
    if args.format == "vbi" or (args.format == "auto" and not args.input.lower().endswith(".t42")):
        from .vbi import read_raw_vbi
        source = read_raw_vbi(args.input, args.vbi_samples, args.vbi_rate, args.vbi_offset)
    else:
        source = read_t42(args.input)

    pages = PageAssembler(correct_hamming=not args.strict_hamming)
    fec = SuperblockDecoder(use_erasures=not args.no_erasures)
    sink = Sink(args.output)

    def handle(sbs):
        for sb in sbs:
            for chunk in fec.decode(sb):
                sink.add(chunk)

    for pk in source:
        handle(pages.feed(pk))
    handle(pages.flush())
    streams, files = sink.close()

    t, f = pages.stats, fec.stats
    print(f"Pakete gelesen:        {t.packets}")
    print(f"  Magazin 8:           {t.packets - t.other_magazine - t.bad_address}")
    print(f"  unlesbare Adresse:   {t.bad_address}")
    print(f"Seiten:                {t.pages} (davon unvollständig: {t.incomplete_pages})")
    print(f"Superblöcke:           {f.superblocks}")
    print(f"Datenzeilen fehlerhaft vor FEC: {f.rows_bad_before}, nach FEC: {f.rows_bad_after}, "
          f"fehlend: {f.rows_missing}")
    print(f"RS-Codewörter korrigiert: {f.codewords_corrected} ({f.symbols_corrected} Byte), "
          f"nicht korrigierbar: {f.codewords_failed}")
    for s in streams:
        print(f"Strom {s['id']}: {s['path']} ({s['bytes']} Byte, Lücken: {s['gaps']})")
    for x in files:
        state = "vollständig" if x["complete"] else f"{x['received']}/{x['size']} Byte"
        print(f"Datei {x['id']}: {x['path']} ({state})")
    print(f"Übersicht: {os.path.join(args.output, 'index.json')}")
    return 0


def cmd_testsignal(args):
    sources = []
    for ident, path in args.stream:
        with open(path, "rb") as fh:
            sources.append(stream_rows(int(ident), fh.read()))
    for ident, path in args.file:
        with open(path, "rb") as fh:
            sources.append(file_rows(int(ident), fh.read(), os.path.basename(path)))
    if not sources:
        print("Mindestens --stream oder --file angeben.", file=sys.stderr)
        return 2
    n = 0
    with open(args.output, "wb") as out:
        for pk in damage(packets(interleave(*sources)), args.drop, args.flip, args.seed):
            out.write(pk)
            n += 1
    print(f"{n} Pakete nach {args.output} geschrieben")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="radiomp3", description="Decoder für r@dio.mp3 / MEGARADIO.mp3 (TV Radio Cast, 2000–2003)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decode", help="Videotext-Mitschnitt dekodieren")
    d.add_argument("input", help=".t42-Datei (42-Byte-Pakete) oder rohe VBI-Daten")
    d.add_argument("-o", "--output", default="radiomp3-out", help="Ausgabeverzeichnis")
    d.add_argument("--format", choices=["auto", "t42", "vbi"], default="auto")
    d.add_argument("--vbi-samples", type=int, default=2048, help="Samples pro VBI-Zeile (Standard: 2048, bttv)")
    d.add_argument("--vbi-rate", type=float, default=35_468_950.0, help="Abtastrate in Hz (Standard: bttv PAL)")
    d.add_argument("--vbi-offset", type=int, default=0, help="Bytes am Dateianfang überspringen")
    d.add_argument("--no-erasures", action="store_true", help="nur Fehlerkorrektur wie der Original-Player")
    d.add_argument("--strict-hamming", action="store_true", help="Hamming 8/4 ohne Einzelbitkorrektur (wie der Player)")
    d.set_defaults(func=cmd_decode)

    t = sub.add_parser("testsignal", help="Testsignal (.t42) erzeugen")
    t.add_argument("-o", "--output", required=True)
    t.add_argument("--stream", nargs=2, action="append", default=[], metavar=("ID", "DATEI"),
                   help="Datei als Live-Strom senden (ID durch 10 teilbar, z. B. 10)")
    t.add_argument("--file", nargs=2, action="append", default=[], metavar=("ID", "DATEI"),
                   help="Datei als Dateiübertragung senden (ID nicht durch 10 teilbar)")
    t.add_argument("--drop", type=float, default=0.0, help="Anteil verlorener Zeilen (0..1)")
    t.add_argument("--flip", type=float, default=0.0, help="Bitfehler-Wahrscheinlichkeit pro Byte")
    t.add_argument("--seed", type=int, default=0)
    t.set_defaults(func=cmd_testsignal)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
