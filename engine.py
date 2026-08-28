import argparse
import json
import os
import subprocess
import sys

import librosa
import numpy as np
import pretty_midi
import soundfile as sf

def run(command):
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def add_note(instrument, pitch, start, end, velocity):
    if end > start + 0.04:
        instrument.notes.append(
            pretty_midi.Note(
                velocity=int(velocity),
                pitch=int(max(0, min(127, pitch))),
                start=float(start),
                end=float(end)
            )
        )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--settings", required=True)

    args = parser.parse_args()
    settings = json.loads(args.settings)

    os.makedirs(args.out, exist_ok=True)

    voice_wav = os.path.join(args.out, "voice.wav")

    # Converte qualquer formato enviado para WAV mono.
    run([
        "ffmpeg",
        "-y",
        "-i",
        args.input,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "22050",
        voice_wav
    ])

    audio, sample_rate = librosa.load(
        voice_wav,
        sr=22050,
        mono=True
    )

    duration = len(audio) / sample_rate

    if duration < 2:
        raise ValueError("Áudio muito curto.")

    audio = librosa.util.normalize(audio)

    # Detecta as notas cantadas.
    frequency, voiced, _ = librosa.pyin(
        audio,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C6"),
        sr=sample_rate,
        frame_length=2048,
        hop_length=256
    )

    melody_midi = np.where(
        np.isnan(frequency),
        np.nan,
        librosa.hz_to_midi(frequency)
    )

    valid_notes = melody_midi[~np.isnan(melody_midi)]

    if len(valid_notes) < 12:
        raise ValueError("Não foi encontrada uma voz afinada suficiente.")

    # Descobre uma tonalidade provável, maior ou menor.
    pitch_classes = np.mod(
        np.rint(valid_notes).astype(int),
        12
    )

    histogram = np.bincount(
        pitch_classes,
        minlength=12
    )

    major_scale = [0, 2, 4, 5, 7, 9, 11]
    minor_scale = [0, 2, 3, 5, 7, 8, 10]

    best = (-1, 0, "major")

    for root in range(12):
        for mode_name, scale in [
            ("major", major_scale),
            ("minor", minor_scale)
        ]:
            score = sum(
                histogram[(root + note) % 12]
                for note in scale
            )

            score -= 0.35 * sum(
                histogram[(root + note) % 12]
                for note in range(12)
                if note not in scale
            )

            if score > best[0]:
                best = (score, root, mode_name)

    _, root, mode = best

    bpm = float(settings["bpm"])
    beat = 60 / bpm
    bar = beat * 4
    bars = max(1, int(np.ceil(duration / bar)))

    # Cria os acordes que pertencem à tonalidade detectada.
    if mode == "major":
        intervals = [0, 2, 4, 5, 7, 9, 11]
        qualities = ["maj", "min", "min", "maj", "maj", "min", "dim"]
    else:
        intervals = [0, 2, 3, 5, 7, 8, 10]
        qualities = ["min", "dim", "maj", "min", "min", "maj", "maj"]

    candidates = []

    for degree in range(7):
        chord_root = (root + intervals[degree]) % 12
        quality = qualities[degree]

        third = 4 if quality == "maj" else 3
        fifth = 6 if quality == "dim" else 7

        triad = [
            chord_root,
            (chord_root + third) % 12,
            (chord_root + fifth) % 12
        ]

        candidates.append((chord_root, triad, quality))

    # Escolhe, em cada compasso, o acorde mais próximo da melodia.
    chosen_chords = []

    for current_bar in range(bars):
        start_frame = int(current_bar * bar * sample_rate / 256)
        end_frame = int(
            min(duration, (current_bar + 1) * bar)
            * sample_rate / 256
        )

        section = melody_midi[start_frame:end_frame]
        section = section[~np.isnan(section)]

        if len(section):
            section_histogram = np.bincount(
                np.mod(np.rint(section).astype(int), 12),
                minlength=12
            )
        else:
            section_histogram = histogram

        scores = [
            sum(section_histogram[note] for note in triad)
            + 0.5 * section_histogram[chord_root]
            for chord_root, triad, quality in candidates
        ]

        chosen_chords.append(
            candidates[int(np.argmax(scores))]
        )

    midi = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    instruments = set(settings.get("instruments", []))

    piano = pretty_midi.Instrument(0, name="Piano")
    pad = pretty_midi.Instrument(89, name="Pad")
    strings = pretty_midi.Instrument(48, name="Cordas")
    bass = pretty_midi.Instrument(33, name="Baixo")
    drums = pretty_midi.Instrument(
        0,
        is_drum=True,
        name="Bateria"
    )
    guitar = pretty_midi.Instrument(24, name="Violão")

    for current_bar, (chord_root, triad, quality) in enumerate(chosen_chords):
        start = current_bar * bar
        end = min(duration, start + bar)

        chord_notes = [
            60 + (note - root) % 12
            for note in triad
        ]

        bass_note = 36 + (chord_root - root) % 12

        if "pad" in instruments:
            for note in chord_notes:
                add_note(pad, note, start, end, 46)

        if "cordas" in instruments:
            for note in chord_notes:
                add_note(strings, note + 12, start, end, 52)

        if "baixo" in instruments:
            add_note(bass, bass_note, start, end, 78)

        if "piano" in instruments:
            add_note(
                piano,
                bass_note + 12,
                start,
                start + beat * 0.9,
                76
            )

            for index in range(8):
                note_start = start + index * beat / 2
                note_end = min(
                    end,
                    note_start + beat * 0.42
                )

                add_note(
                    piano,
                    chord_notes[index % 3],
                    note_start,
                    note_end,
                    60 + (index % 2) * 8
                )

        if "violao" in instruments:
            for index in range(8):
                note_start = start + index * beat / 2
                note_end = min(end, note_start + 0.22)

                for note in chord_notes:
                    add_note(
                        guitar,
                        note,
                        note_start,
                        note_end,
                        50
                    )

        if "bateria" in instruments:
            for index in range(8):
                hit_time = start + index * beat / 2

                if hit_time < end:
                    add_note(
                        drums,
                        42,
                        hit_time,
                        hit_time + 0.05,
                        42
                    )

            for index in [0, 2]:
                hit_time = start + index * beat

                if hit_time < end:
                    add_note(
                        drums,
                        36,
                        hit_time,
                        hit_time + 0.08,
                        92
                    )

            for index in [1, 3]:
                hit_time = start + index * beat

                if hit_time < end:
                    add_note(
                        drums,
                        38,
                        hit_time,
                        hit_time + 0.08,
                        70
                    )

    available_instruments = [
        ("piano", piano),
        ("pad", pad),
        ("cordas", strings),
        ("baixo", bass),
        ("bateria", drums),
        ("violao", guitar)
    ]

    for name, instrument in available_instruments:
        if name in instruments:
            midi.instruments.append(instrument)

    midi_path = os.path.join(args.out, "arranjo.mid")
    midi.write(midi_path)

    soundfont = "/usr/share/sounds/sf2/FluidR3_GM.sf2"
    instrumental_wav = os.path.join(args.out, "instrumental.wav")

    # Transforma o MIDI em áudio.
    run([
        "fluidsynth",
        "-ni",
        soundfont,
        midi_path,
        "-F",
        instrumental_wav,
        "-r",
        "44100"
    ])

    final_wav = os.path.join(args.out, "musica_final.wav")

    # Mantém a voz original, se o usuário tiver escolhido essa opção.
    if settings.get("keepVoice", True):
        run([
            "ffmpeg",
            "-y",
            "-i",
            instrumental_wav,
            "-i",
            voice_wav,
            "-filter_complex",
            "[0:a]volume=0.48[i];"
            "[1:a]volume=1.35[v];"
            "[i][v]amix=inputs=2:duration=longest:normalize=0,"
            "alimiter=limit=0.95",
            "-ar",
            "44100",
            final_wav
        ])
    else:
        run([
            "ffmpeg",
            "-y",
            "-i",
            instrumental_wav,
            "-ar",
            "44100",
            final_wav
        ])

    keys = [
        "C", "C#", "D", "D#", "E", "F",
        "F#", "G", "G#", "A", "A#", "B"
    ]

    print(json.dumps({
        "key": keys[root] + (" maior" if mode == "major" else " menor"),
        "bpm": round(bpm),
        "duration": round(duration, 1),
        "bars": bars
    }))

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
