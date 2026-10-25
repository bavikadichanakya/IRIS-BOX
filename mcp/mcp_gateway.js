import express from 'express';
import cors from 'cors';
import { spawn } from 'child_process';
import { createMcpExpressApp } from '@modelcontextprotocol/express';

const app = createMcpExpressApp({ host: '0.0.0.0' });
app.use(cors());
app.use(express.json());

// Spawn the memory server engine
const child = spawn('npx', ['-y', '@modelcontextprotocol/server-memory'], {
    stdio: ['pipe', 'pipe', 'inherit'],
    shell: true
});

let activeRes = null;

// SSE route for connection and messages
app.all('/sse', (req, res) => {
    if (req.method === 'HEAD' || req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    if (req.method === 'POST') {
        if (req.body && req.body.method === 'initialize') {
            return res.status(200).json({
                jsonrpc: "2.0",
                id: req.body.id,
                result: {
                    protocolVersion: "2024-11-05",
                    capabilities: { tools: {}, resources: {} },
                    serverInfo: { name: "memory-server-gateway", version: "1.0.0" }
                }
            });
        }
        child.stdin.write(JSON.stringify(req.body) + '\n');
        return res.status(200).end();
    }

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.status(200);
    activeRes = res;
    console.log('Client connected to MCP Gateway SSE stream.');
});

// Cloud OAuth security routes
app.all('/.well-known/oauth-protected-resource', (req, res) => res.sendStatus(200));
app.all('/.well-known/oauth-protected-resource/sse', (req, res) => res.sendStatus(200));

app.post('/message', (req, res) => {
    child.stdin.write(JSON.stringify(req.body) + '\n');
    res.status(200).end();
});

child.stdout.on('data', (data) => {
    if (activeRes) {
        activeRes.write(`data: ${data.toString()}\n\n`);
    }
});

const PORT = process.env.PORT || 6274;
app.listen(PORT, () => console.log(`MCP Gateway running on port ${PORT}!`));
