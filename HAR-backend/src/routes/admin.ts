import { Router, Request, Response, NextFunction } from 'express';
import { dbAll } from '../database';

const router = Router();

// Optional simple guard using ADMIN_TOKEN for dev environments
const adminGuard = (req: Request, res: Response, next: NextFunction) => {
  const tokenRequired = process.env.ADMIN_TOKEN;
  if (!tokenRequired) return next();

  const headerToken = req.header('x-admin-token');
  const queryToken = (req.query.token as string) || '';
  if (headerToken === tokenRequired || queryToken === tokenRequired) return next();

  res.status(401).send('Unauthorized');
};

router.get('/admin/users.json', adminGuard, async (_req: Request, res: Response) => {
  try {
    const users = await dbAll('SELECT id, username, created_at FROM users ORDER BY created_at DESC LIMIT 100');
    res.json(users);
  } catch (err) {
    res.status(500).json({ message: 'Failed to load users' });
  }
});

router.get('/admin/esp-devices.json', adminGuard, async (_req: Request, res: Response) => {
  try {
    const esps = await dbAll('SELECT id, is_connected as isConnected FROM esp_devices ORDER BY id ASC LIMIT 200');
    res.json(esps);
  } catch (err) {
    res.status(500).json({ message: 'Failed to load esp devices' });
  }
});

router.get('/admin', adminGuard, async (_req: Request, res: Response) => {
  try {
    const users = await dbAll('SELECT id, username, created_at FROM users ORDER BY created_at DESC LIMIT 100');
    const esps = await dbAll('SELECT id, is_connected as isConnected FROM esp_devices ORDER BY id ASC LIMIT 200');

    const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>HAR Admin</title>
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 16px; }
      h1 { margin: 0 0 8px 0; }
      h2 { margin-top: 24px; }
      table { border-collapse: collapse; width: 100%; margin-top: 8px; }
      th, td { border: 1px solid #ddd; padding: 8px; font-size: 14px; }
      th { background: #f7f7f7; text-align: left; }
      .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; }
      .ok { background: #e7f7ee; color: #0f7a3b; }
      .bad { background: #fdecea; color: #b3261e; }
      .unk { background: #eef2f7; color: #334155; }
      .grid { display: grid; grid-template-columns: 1fr; gap: 24px; }
      @media (min-width: 900px) { .grid { grid-template-columns: 1fr 1fr; } }
      .tip { color: #475569; font-size: 13px; }
      .header { display:flex; align-items:center; justify-content:space-between; }
      code { background:#f3f4f6; padding:2px 6px; border-radius:4px; }
    </style>
  </head>
  <body>
    <div class="header">
      <h1>HAR Admin</h1>
      <div class="tip">Health: <span class="pill ok">ok</span></div>
    </div>
    <div class="tip">Set <code>ADMIN_TOKEN</code> env and append <code>?token=YOUR_TOKEN</code> to protect this page.</div>

    <div class="grid">
      <section>
        <h2>Users (${users.length})</h2>
        <table>
          <thead>
            <tr><th>ID</th><th>Username</th><th>Created</th></tr>
          </thead>
          <tbody>
            ${users.map((u: any) => `<tr><td>${u.id}</td><td>${u.username}</td><td>${u.created_at ?? ''}</td></tr>`).join('')}
          </tbody>
        </table>
      </section>
      <section>
        <h2>ESP Devices (${esps.length})</h2>
        <table>
          <thead>
            <tr><th>ID</th><th>Status</th></tr>
          </thead>
          <tbody>
            ${esps.map((e: any) => {
              const status = e.isConnected === 1 || e.isConnected === true ? '<span class="pill ok">connected</span>' : (e.isConnected === 0 || e.isConnected === false ? '<span class="pill bad">disconnected</span>' : '<span class="pill unk">unknown</span>');
              return `<tr><td>${e.id}</td><td>${status}</td></tr>`;
            }).join('')}
          </tbody>
        </table>
      </section>
    </div>
  </body>
</html>`;

    res.status(200).contentType('text/html').send(html);
  } catch (err) {
    res.status(500).send('Failed to render admin UI');
  }
});

export default router;
