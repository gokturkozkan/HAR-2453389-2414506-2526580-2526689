import { Router, Request, Response } from 'express';
import { dbAll, dbRun, dbGet } from '../database.js';
import { authMiddleware } from '../middleware/auth.js';
import { EspDevice } from '../types/index.js';

const router = Router();

// Apply auth middleware to all routes
router.use(authMiddleware);

// Get ESP status
router.get('/esp-status', async (req: Request, res: Response) => {
  try {
    const devices = await dbAll(`
      SELECT 
        id, 
        is_connected as isConnected,
        last_heartbeat,
        created_at
      FROM esp_devices
      ORDER BY id ASC
    `);

    res.json(devices);
  } catch (error) {
    console.error('Error fetching ESP status:', error);
    res.status(500).json({ message: 'Error fetching ESP status' });
  }
});

// Update ESP device status (for ESP devices to send heartbeats)
router.post('/esp-status/:id', async (req: Request, res: Response) => {
  try {
    const deviceId = parseInt(req.params.id, 10);
    const { isConnected } = req.body;

    if (isNaN(deviceId)) {
      res.status(400).json({ message: 'Invalid device ID' });
      return;
    }

    // Check if device exists
    const device = await dbGet('SELECT id FROM esp_devices WHERE id = ?', [deviceId]);

    if (!device) {
      // Create new device
      await dbRun(
        'INSERT INTO esp_devices (id, is_connected, last_heartbeat) VALUES (?, ?, CURRENT_TIMESTAMP)',
        [deviceId, isConnected ? 1 : 0]
      );
    } else {
      // Update existing device
      await dbRun(
        'UPDATE esp_devices SET is_connected = ?, last_heartbeat = CURRENT_TIMESTAMP WHERE id = ?',
        [isConnected ? 1 : 0, deviceId]
      );
    }

    res.json({ message: 'Device status updated', id: deviceId });
  } catch (error) {
    console.error('Error updating ESP status:', error);
    res.status(500).json({ message: 'Error updating ESP status' });
  }
});

// Initialize ESP devices (admin endpoint - create sample devices)
router.post('/esp-devices/init', async (req: Request, res: Response) => {
  try {
    const { count = 2 } = req.body;

    for (let i = 1; i <= count; i++) {
      const exists = await dbGet('SELECT id FROM esp_devices WHERE id = ?', [i]);
      if (!exists) {
        await dbRun(
          'INSERT INTO esp_devices (id, is_connected) VALUES (?, ?)',
          [i, 0]
        );
      }
    }

    res.json({ message: `Initialized ${count} ESP devices` });
  } catch (error) {
    console.error('Error initializing ESP devices:', error);
    res.status(500).json({ message: 'Error initializing ESP devices' });
  }
});

export default router;
