const http = require('http');

process.on('uncaughtException', (err) => {
  console.error('Port 8502 proxy caught error (prevented crash):', err.message);
});

const server = http.createServer((req, res) => {
  req.on('error', (err) => {
    console.error('Req error:', err.message);
  });
  res.on('error', (err) => {
    console.error('Res error:', err.message);
  });

  const options = {
    hostname: '127.0.0.1',
    port: 8501,
    path: req.url,
    method: req.method,
    headers: {
      ...req.headers,
      host: '127.0.0.1:8501',
    },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });

  proxyReq.on('error', (err) => {
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'text/plain' });
      res.end('FinovaLabs Streamlit Proxy Error: ' + err.message);
    }
  });

  if (['GET', 'HEAD', 'OPTIONS'].includes(req.method)) {
    proxyReq.end();
  } else {
    req.pipe(proxyReq);
  }
});

// Streamlit WebSocket upgrade for _stcore/stream
server.on('upgrade', (req, socket, head) => {
  socket.on('error', () => {
    // silently swallow socket reset
  });

  const proxyReq = http.request({
    hostname: '127.0.0.1',
    port: 8501,
    path: req.url,
    method: req.method,
    headers: {
      ...req.headers,
      host: '127.0.0.1:8501',
    },
  });

  proxyReq.on('upgrade', (proxyRes, proxySocket, proxyHead) => {
    socket.on('error', () => {
      try { proxySocket.destroy(); } catch (_) {}
    });
    proxySocket.on('error', () => {
      try { socket.destroy(); } catch (_) {}
    });

    try {
      socket.write(
        `HTTP/${proxyRes.httpVersion} ${proxyRes.statusCode} ${proxyRes.statusMessage}\r\n` +
        Object.keys(proxyRes.headers).map(k => `${k}: ${proxyRes.headers[k]}`).join('\r\n') +
        '\r\n\r\n'
      );
      proxySocket.pipe(socket);
      socket.pipe(proxySocket);
    } catch (_) {}
  });

  proxyReq.on('error', () => {
    try { socket.destroy(); } catch (_) {}
  });

  proxyReq.end();
});

server.listen(8502, '127.0.0.1', () => {
  console.log('FinovaLabs Port 8502 proxy listening -> 8501');
});
