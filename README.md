# radiomp3-decoder

Ein Decoder in Python für die MP3-Datenübertragung von **r@dio.mp3** (Musicplay, 2000–2001) und **MEGARADIO.mp3** (Megaradio/NBC GIGA, 2002–2003). Beide Sender schickten MP3-Musik, Cover und HTML-Seiten in der Austastlücke (VBI) von NBC Europe. Das Verfahren hieß „TV Radio Cast“, die Empfangssoftware stammte von RapidSolution.

Der Decoder macht aus einem Videotext-Mitschnitt dieser Sendungen wieder MP3-Dateien. Das Format wurde aus dem Original-Player *Megaradio.mp3 1.2.0.6* (Dezember 2002) rekonstruiert, siehe [docs/FORMAT.md](docs/FORMAT.md).

## Was er kann

- **Eingabe:** `.t42`-Dateien mit 42-Byte-Videotextpaketen, wie sie z. B. [vhs-teletext](https://github.com/ali1234/vhs-teletext) aus VHS-Aufnahmen gewinnt. Außerdem rohe 8-Bit-VBI-Abtastwerte, etwa von Linux bttv (`/dev/vbi`). Dafür bringt der Decoder einen eigenen Software-Slicer mit.
- **Fehlerkorrektur** wie im Original: Reed-Solomon RS(210,182) über 15 Videotextseiten und Adler-32 pro Zeile. Zusätzlich nutzt er fehlende Zeilen als bekannte Fehlstellen (Erasures). So kann er doppelt so viele verlorene Bytes reparieren wie der Original-Player.
- **Ausgabe:** Live-Audiostrom als `.mp3` und übertragene Dateien (Album-Tracks, Cover, HTML, `stream.ini`) im Ordner `files/`. Unvollständige Dateien landen als `.partial`, und `index.json` listet alles auf.
- **Testsender:** `radiomp3 testsignal` erzeugt ein Signal im Originalformat, auch mit simulierten Empfangsfehlern.

## Was er nicht kann

Die Premium-Alben von MEGARADIO.mp3 (ab 16.09.2002) sind mit Blowfish verschlüsselt. Jeder Titel hat einen eigenen Schlüssel, und die Schlüsseldateien waren an den Rechner des Abonnenten gebunden. Ohne diese damaligen `.key`-Dateien bleiben diese Titel unlesbar. Der Decoder schreibt sie trotzdem heraus. Das übrige Programm war unverschlüsselt.

## Installation

```bash
pip install .            # nur .t42
pip install .[vbi]       # mit Slicer für rohe VBI-Daten (numpy)
```

Python 3.9 oder neuer, sonst keine Abhängigkeiten.

## Benutzung

```bash
# Mitschnitt dekodieren
radiomp3 decode aufnahme.t42 -o ausgabe/

# rohe VBI-Daten (bttv: 2048 Samples/Zeile, 35,468950 MHz)
radiomp3 decode capture.vbi --format vbi -o ausgabe/

# Testsignal mit 2 % verlorenen Zeilen erzeugen und wieder dekodieren
radiomp3 testsignal -o test.t42 --stream 10 lied.mp3 --file 23 cover.jpg --drop 0.02
radiomp3 decode test.t42 -o test-out/
```

Optionen für `decode`:

| Option | Bedeutung |
|---|---|
| `--format auto\|t42\|vbi` | Eingabeformat (Standard: nach Dateiendung) |
| `--vbi-samples`, `--vbi-rate`, `--vbi-offset` | Zeilenlänge, Abtastrate und Kopfbytes der VBI-Rohdaten |
| `--no-erasures` | nur Fehlerkorrektur wie der Original-Player |
| `--plain-header` | Zeilenkopf ohne XOR 0xA5, so in einer VHS-Aufnahme von NBC GIGA gesehen |
| `--strict-hamming` | Hamming 8/4 ohne Einzelbitkorrektur, wie der Player |

## Wie gut ist das abgesichert?

- Die Reed-Solomon-Parität ist byte-identisch mit der des Original-Players (`tests/data/rs_vector_player.bin` wurde mit dessen Code erzeugt).
- Das Referenzsignal `tests/data/reference_signal.t42` lief durch die Empfangsroutinen des Original-Players (per CPU-Emulation, nicht ausgeführt unter Windows). Superblöcke und alle extrahierten Datenstücke stimmen exakt überein (`tests/data/player_reference.json`).
- Echte Mitschnitte von 2000–2003 standen noch nicht zur Verfügung. Ein paar Felder sind noch nicht vollständig verstanden, siehe [docs/FORMAT.md](docs/FORMAT.md#offene-punkte). Wer eine VHS-Aufnahme von NBC Europe/NBC GIGA aus dieser Zeit hat: Die Austastlücke ist oft noch mit drauf.

## Tests

```bash
pip install pytest numpy
pytest
```
