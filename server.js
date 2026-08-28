import express from 'express';
import multer from 'multer';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { v4 as uuid } from 'uuid';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const port = Number(process.env.PORT || 3000);

const jobs = path.join(__dirname, 'data', 'jobs');
const uploads = path.join(__dirname, 'data', 'uploads');

fs.mkdirSync(jobs, { recursive: true });
fs.mkdirSync(uploads, { recursive: true });

const maxMb = Number(process.env.MAX_UPLOAD_MB || 25);

const allowed = new Set([
  'audio/mpeg',
  'audio/wav',
  'audio/x-wav',
  'audio/mp4',
  'audio/x-m4a',
  'audio/ogg',
  'audio/webm',
  'video/mp4'
]);

const upload = multer({
  dest: uploads,
  limits: { fileSize: maxMb * 1024 * 1024 },
  fileFilter: (_req, file, cb) => {
    const accepted =
      allowed.has(file.mimetype) ||
      /\.(mp3|wav|m4a|ogg|mp4|webm)$/i.test(file.originalname);

    cb(null, accepted);
  }
});

app.use(express.static(path.join(__dirname, 'public')));
app.use('/files', express.static(jobs, { fallthrough: false }));

app.post('/api/generate', upload.single('audio'), (req, res) => {
  if (!req.file) {
    return res.status(400).json({
      error: 'Envie um arquivo de áudio: MP3, WAV, M4A, OGG, MP4 ou WebM.'
    });
  }

  let instruments = [];

  try {
    instruments = JSON.parse(req.body.instruments || '[]');
  } catch {
    return res.status(400).json({
      error: 'Instrumentos inválidos.'
    });
  }

  const settings = {
    style: req.body.style || 'gospel',
    bpm: Number(req.body.bpm || 72),
    keepVoice: req.body.keepVoice === 'true',
    instruments
  };

  if (
    !Number.isFinite(settings.bpm) ||
    settings.bpm < 45 ||
    settings.bpm > 180
  ) {
    return res.status(400).json({
      error: 'O BPM deve estar entre 45 e 180.'
    });
  }

  const id = uuid();
  const jobDir = path.join(jobs, id);

  fs.mkdirSync(jobDir, { recursive: true });

  const args = [
    path.join(__dirname, 'engine.py'),
    '--input',
    req.file.path,
    '--out',
    jobDir,
    '--settings',
    JSON.stringify(settings)
  ];

  const py = spawn('python3', args, { timeout: 240000 });

  let stderr = '';
  let stdout = '';
  let responded = false;

  py.stdout.on('data', (data) => {
    stdout += data.toString();
  });

  py.stderr.on('data', (data) => {
    stderr += data.toString();
  });

  py.on('error', (error) => {
    if (responded) return;
    responded = true;

    res.status(500).json({
      error: 'Não foi possível iniciar o motor de áudio.',
      details: error.message
    });
  });

  py.on('close', (code) => {
    fs.rm(req.file.path, { force: true }, () => {});

    if (responded) return;
    responded = true;

    if (code !== 0) {
      return res.status(422).json({
        error:
          'Não foi possível extrair uma melodia clara desse áudio. Tente gravar apenas a voz, sem instrumentos e sem muito ruído.',
        details: stderr.slice(-500)
      });
    }

    try {
      const result = JSON.parse(stdout.trim().split('\n').at(-1));

      return res.json({
        ...result,
        audioUrl: `/files/${id}/musica_final.wav`,
        midiUrl: `/files/${id}/arranjo.mid`
      });
    } catch {
      return res.status(500).json({
        error: 'O motor de música retornou uma resposta inválida.',
        details: stdout.slice(-300)
      });
    }
  });
});

app.use((error, _req, res, _next) => {
  if (error instanceof multer.MulterError && error.code === 'LIMIT_FILE_SIZE') {
    return res.status(413).json({
      error: `O áudio pode ter no máximo ${maxMb} MB.`
    });
  }

  return res.status(500).json({
    error: 'Ocorreu um erro inesperado no servidor.'
  });
});

app.listen(port, () => {
  console.log(`Voz em Música disponível na porta ${port}`);
});
