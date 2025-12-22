import { Router, Request, Response } from 'express';
import { dbAll, dbRun, dbGet } from '../database';
import { authMiddleware } from '../middleware/auth';
import { EspDevice } from '../types/index';

const router = Router();

// Apply auth middleware to all routes
router.use(authMiddleware);

// Get ESP status (list or single by query ?id=)
router.get('/esp-status', async (req: Request, res: Response) => {
  try {
    const idParam = req.query.id as string | undefined;
    if (idParam) {
      const deviceId = parseInt(idParam, 10);
      if (isNaN(deviceId)) {
        res.status(400).json({ message: 'Invalid device ID' });
        return;
      }

      const row = await dbGet(
        'SELECT id, is_connected as isConnected FROM esp_devices WHERE id = ?',
        [deviceId]
      );
      if (!row) {
        res.status(404).json({ message: 'Device not found' });
        return;
      }
      const device: EspDevice = { id: row.id, isConnected: row.isConnected === 1 };
      res.json(device);
      return;
    }

    const rows = await dbAll(
      'SELECT id, is_connected as isConnected FROM esp_devices ORDER BY id ASC'
    );
    const devices: EspDevice[] = (rows as any[]).map((r) => ({ id: r.id, isConnected: r.isConnected === 1 }));
    res.json(devices);
  } catch (error) {
    console.error('Error fetching ESP status:', error);
    res.status(500).json({ message: 'Error fetching ESP status' });
  }
});

// Get list of ESP device IDs
router.get('/esp', async (_req: Request, res: Response) => {
  try {
    const rows = await dbAll('SELECT id FROM esp_devices ORDER BY id ASC');
    const ids = rows.map((r: any) => ({ id: r.id }));
    res.json(ids);
  } catch (error) {
    console.error('Error fetching ESP ids:', error);
    res.status(500).json({ message: 'Error fetching ESPs' });
  }
});

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
        'INSERT INTO esp_devices (id, is_connected) VALUES (?, ?)',
        [deviceId, isConnected ? 1 : 0]
      );
    } else {
      // Update existing device
      await dbRun(
        'UPDATE esp_devices SET is_connected = ? WHERE id = ?',
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
