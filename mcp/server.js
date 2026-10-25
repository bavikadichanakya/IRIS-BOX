import express from 'express';
import cors from 'cors';
import { spawn } from 'child_process';

const app = express();
app.use(cors());
app.use(express.json());

// Spawn the memory server in standard I/O mode underneath
const child = spawn('npx', ['-y', '@modelcontextprotocol/server-memory'], {
    stdio: ['pipe', 'pipe', 'inherit'],
    shell: true
});

let activeRes = null;

// Handle the validation pings and stream connection
app.all('/sse', (req, res) => {
    if (req.method === 'HEAD') {
        return res.status(200).end(); // Satisfy the Gemini validation ping instantly
    }

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.status(200);
    activeRes = res;
    console.log('Gemini connected to the SSE stream.');
});

// Route messaging traffic back down to the memory engine
app.post('/message', (req, res) => {
    child.stdin.write(JSON.stringify(req.body) + '\n');
    res.status(200).end();
});

child.stdout.on('data', (data) => {
    if (activeRes) {
        activeRes.write(`data: ${data.toString()}\n\n`);
    }
});

app.listen(6274, () => console.log('Stable MCP HTTP Bridge running on port 6274!'));
