import { Router, Request, Response } from 'express';
import bcrypt from 'bcrypt';

import { dbGet, dbRun } from '../database.js';
import { authMiddleware, requireAuth, generateToken } from '../middleware/auth.js';

const router = Router();

// Attach auth middleware so req.user is populated when a valid Bearer token is provided
router.use(authMiddleware);

// Update the current user's username
router.post('/user/update', async (req: Request, res: Response) => {
  try {
    const { credentials, userId } = req.body as {
      credentials?: { username?: string };
      userId?: string;
    };

    const nextUsername = credentials?.username?.trim();

    if (!nextUsername) {
      res.status(400).json({ message: 'Username is required' });
      return;
    }

    if (!userId) {
      res.status(400).json({ message: 'User ID is required' });
      return;
    }

    // Check if the user exists
    const user = await dbGet('SELECT id, username FROM users WHERE id = ?', [userId]);
    if (!user) {
      res.status(404).json({ message: 'User not found' });
      return;
    }

    // Check if username is already taken by another user
    const existing = await dbGet('SELECT id FROM users WHERE username = ? AND id != ?', [nextUsername, userId]);
    if (existing) {
      res.status(409).json({ message: 'Username already taken' });
      return;
    }

    // Update the username
    await dbRun('UPDATE users SET username = ? WHERE id = ?', [nextUsername, userId]);

    // Generate a new token with updated username
    const token = generateToken(userId, nextUsername);

    res.json({
      token,
      user: {
        id: userId,
        username: nextUsername,
      },
    });
  } catch (error) {
    console.error('Error updating user:', error);
    res.status(500).json({ message: 'Error updating credentials' });
  }
});

export default router;