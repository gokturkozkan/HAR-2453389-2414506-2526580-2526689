import { Router, Request, Response } from 'express';
import { dbAll, dbGet } from '../database.js';

const router = Router();

// Returns a single label string and corresponding image from the labels and unity_images tables
router.get('/label', async (_req: Request, res: Response) => {
  try {
    // Get the label from labels table (seeded with 'sitting')
    const row = await dbGet('SELECT name FROM labels ORDER BY id ASC LIMIT 1');
    if (!row || !row.name) {
      res.status(404).json({ message: 'No label found' });
      return;
    }

    const label = row.name;

    // Find the corresponding image in unity_images with matching name (e.g., "sitting.png")
    const imageRow = await dbGet('SELECT data FROM unity_images WHERE name = ?', [`${label}.png`]);
    
    if (!imageRow || !imageRow.data) {
      res.status(404).json({ message: `Image not found for label: ${label}` });
      return;
    }

    // Convert image data to base64
    const imageBase64 = imageRow.data.toString('base64');

    res.json({
      label,
      image: imageBase64,
    });
  } catch (error) {
    console.error('Error fetching label and image:', error);
    res.status(500).json({ message: 'Error fetching label and image' });
  }
});

export default router;