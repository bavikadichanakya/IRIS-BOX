# IRIS Model Context Protocol (MCP) Gateway & Bridge

This directory contains the HTTP/SSE bridge services connecting Model Context Protocol (MCP) clients (such as Antigravity, Gemini, or Claude Desktop) to local MCP servers (such as `@modelcontextprotocol/server-memory`).

---

## 🚀 Quickstart

### 1. Install Dependencies
```bash
npm install
```

### 2. Run MCP Gateway (Port 6274)
```bash
npm start
```
This launches `mcp_gateway.js` on port `6274`, providing:
- **SSE Stream endpoint:** `GET /sse`
- **JSON-RPC Message endpoint:** `POST /message`
- Underneath, it manages an instance of `@modelcontextprotocol/server-memory` over stdio.

---

## 📁 Files Overview

- **`mcp_gateway.js`**: Express-based SSE and HTTP gateway with protocol initialization handling.
- **`bridge.js`**: MCP SDK-based SSE server transport bridge (`SSEServerTransport`).
- **`server.js`**: Lightweight Express SSE stream bridge.
- **`mcp_config.json`**: Client configuration schema snippet for standard MCP client desktop tools.
- **`mcp_bridge.js`**: Standard memory server configuration definition.
