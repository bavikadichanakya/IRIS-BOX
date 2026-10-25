import express from 'express';
import { spawn } from 'child_process';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';

const app = express();
let sseTransport = null;

// Spawn the official memory server engine underneath
const child = spawn('npx', ['-y', '@modelcontextprotocol/server-memory'], {
    stdio: ['pipe', 'pipe', 'inherit'],
    shell: true
});

app.get('/sse', (req, res) => {
    console.log('Gemini connected to SSE channel');
    sseTransport = new SSEServerTransport('/message', res);

    // Route web streams down to the child process paths
    req.on('close', () => console.log('Connection closed'));
});

app.post('/message', express.json(), (req, res) => {
    if (sseTransport) {
        child.stdin.write(JSON.stringify(req.body) + '\n');
        res.status(200).end();
    } else {
        res.status(400).send('No active SSE session');
    }
});

child.stdout.on('data', (data) => {
    if (sseTransport) {
        // Send data chunks straight back to the cloud front-end
        const lines = data.toString().split('\n');
        lines.forEach(line => {
            if (line.trim()) sseTransport.send(JSON.parse(line));
        });
    }
});

app.listen(6274, () => console.log('Stable MCP Web Bridge live on port 6274!'));
