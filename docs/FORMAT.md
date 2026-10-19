# Übertragungsformat TV Radio Cast (r@dio.mp3 / MEGARADIO.mp3)

Rekonstruiert durch statische Analyse von `Megaradio.mp3.exe` 1.2.0.6 (RapidSolution Software AG, 09.12.2002). Adressen beziehen sich auf dieses Programm (Image-Base 0x400000).

## Physikalische Ebene

- Sender: NBC Europe (später NBC GIGA), analog im Kabel und über Hotbird 13° Ost.
- Die Daten sind gewöhnliche **Videotext-Zeilen nach ETS 300 706** mit 6,9375 Mbit/s, Clock-Run-in `0x55 0x55` und Framing Code `0x27`.
- Der Player las 16 VBI-Zeilen pro Halbbild als Rohsignal von einem BT848/BT878 (direkt über WinDriver, eigenes RISC-DMA-Programm, 2044 Samples pro Zeile) und schnitt die Bits in Software (`0x432300`). Alternativ ging es über den Microsoft „WST Codec“ und einen DirectShow-Dump-Filter.

## Ebene 1: Videotext-Paket (42 Byte)

| Byte | Inhalt |
|---|---|
| 0–1 | MRAG, Hamming 8/4: Magazin = 0 (also Magazin 8), Paketnummer 0–23 |
| 2… | je nach Paketnummer, siehe unten |

## Ebene 2: Datenseite (896 Byte)

| Paket | Byte 2 | Byte 3 | Nutzdaten |
|---|---|---|---|
| 0 | normale Seitenkopfzeile (Seitennummer, Subcode), wird nicht ausgewertet | | – |
| 1 | H(Zeilenindex 1–15) | H(aux) | Byte 4–41: 38 Byte → Seitenbyte 0–37 |
| 2–23 | H(Zeilenindex) | | Byte 3–41: 39 Byte → Seitenbyte 38 + (n−2)·39 |

38 + 22·39 = 896. Der Player verlangte lückenlos aufeinanderfolgende Pakete (`0x431f60`, `0x4321e0`, `0x432140`). Dieser Decoder ordnet jedes Paket über seinen eigenen Zeilenindex ein.

## Ebene 3: Superblock (15 Seiten, 13.440 Byte)

- Zeilenindex 1–13: Datenzeilen, 14–15: Paritätsfläche (1.792 Byte).
- Ein Superblock ist fertig, wenn Seite 15 vollständig ist oder eine neue Seite 1 beginnt.
- **Reed-Solomon** (`CFec`, `0x466130`/`0x466260`, Bibliothek „rscode“): GF(256) mit Polynom 0x11D, 28 Paritätsbytes, Nullstellen α¹…α²⁸. Spalte c (0–63) besteht aus den Bytes c·14 … c·14+13 aller 13 Datenzeilen (182 Byte) und hat ihre Parität bei Paritätsfläche c·28 … c·28+27. Seite 14 enthält also die Parität der Spalten 0–31, Seite 15 die der Spalten 32–63.
- **Adler-32** pro Datenzeile in Byte 10–13 (little-endian), gerechnet über die ganze Zeile mit diesen 4 Byte auf 0. Der Player prüft vor und nach RS und behält die bessere Variante.

## Ebene 4: Datenzeile (896 Byte)

| Byte | Inhalt |
|---|---|
| 0–9 | Kopf, jedes Byte XOR 0xA5 |
| | 0–1 Kennung (u16 LE) |
| | 2–5 Position (u32 LE) |
| | 6–9 Gesamtlänge (u32 LE) |
| 10–13 | Adler-32 |
| 14–… | abhängig von der Kennung |

Verteilung (`0x432db0` ff.):
- **Kennung 100:** wird ignoriert (Füllzeile).
- **Kennung ≠ 0 und durch 10 teilbar:** Live-Strom. Nutzdaten ab Byte 16, Länge min(880, Gesamtlänge − Position).
- **Sonst:** Datei. Byte 14–37 Dateiinfo (24 Byte), Nutzdaten ab Byte 38, höchstens 858 Byte.

## Verschlüsselung (nur Premium)

- Blowfish, ECB, 8-Byte-Blöcke (`0x447be0`, `0x447fe0`, `0x448670`).
- Pro Titel ein 72-Byte-Schlüssel aus einer `.key`-Datei. Er ist seinerseits mit einem Blowfish-Schlüssel aus dem Hardware-Fingerabdruck des registrierten Rechners verschlüsselt (MAC über NetBIOS, BIOS, Festplatte, Registrierungsdaten; `0x434140`).
- Den Titel findet der Player über eine 5-Byte-Track-ID im Datenstrom.

## Offene Punkte

- Bedeutung von `aux` in Paket 1 (Hamming-Nibble, Player akzeptiert 1–16).
- Aufbau der 24 Byte Dateiinfo (vermutlich Name oder Track-ID). Der Decoder speichert sie in `index.json` als `info_hex`.
- Die 2 Byte 14–15 in Stromzeilen.
- Welche Seitennummer in Magazin 8 benutzt wurde (wird nicht geprüft).
- Ob „Gesamtlänge“ beim Live-Strom wirklich eine Länge ist oder nur eine laufende Marke.
