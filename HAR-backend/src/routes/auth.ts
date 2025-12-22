import { Router, Request, Response } from 'express';
import { dbGet, dbRun } from '../database.js';
import { generateToken } from '../middleware/auth.js';
import bcrypt from 'bcrypt';
import { v4 as uuidv4 } from 'uuid';
import { LoginRequest, AuthResponse } from '../types/index.js';

const router = Router();

// Register endpoint
router.post('/register', async (req: Request, res: Response) => {
  try {
    const { credentials } = req.body as LoginRequest;

    if (!credentials || !credentials.username || !credentials.password) {
      res.status(400).json({ message: 'Username and password required' });
      return;
    }

    // Check if user already exists
    const existingUser = await dbGet('SELECT id FROM users WHERE username = ?', [credentials.username]);
    if (existingUser) {
      res.status(409).json({ message: 'User already exists' });
      return;
    }

    // Hash password
    const hashedPassword = await bcrypt.hash(credentials.password, 10);
    const userId = uuidv4();

    // Create user
    await dbRun(
      'INSERT INTO users (id, username, password) VALUES (?, ?, ?)',
      [userId, credentials.username, hashedPassword]
    );

    const token = generateToken(userId, credentials.username);

    const response: AuthResponse = {
      token,
      user: {
        id: userId,
        username: credentials.username,
      },
    };

    res.status(201).json(response);
  } catch (error) {
    console.error('Registration error:', error);
    res.status(500).json({ message: 'Error creating account' });
  }
});

// Login endpoint
router.post('/login', async (req: Request, res: Response) => {
  try {
    console.log("api request received: login")
    const { credentials } = req.body as LoginRequest;

    if (!credentials || !credentials.username || !credentials.password) {
      res.status(400).json({ message: 'Username and password required' });
      return;
    }

    // Find user
    const user = await dbGet('SELECT id, username, password FROM users WHERE username = ?', [
      credentials.username,
    ]) as { id: string; username: string; password: string } | undefined;

    if (!user) {
      res.status(401).json({ message: 'Invalid username or password' });
      return;
    }

    // Verify password
    const passwordValid = await bcrypt.compare(credentials.password, user.password);
    if (!passwordValid) {
      res.status(401).json({ message: 'Invalid username or password' });
      return;
    }

    const token = generateToken(user.id, user.username);

    const response: AuthResponse = {
      token,
      user: {
        id: user.id,
        username: user.username,
      },
    };

    res.json(response);
  } catch (error) {
    console.error('Login error:', error);
    res.status(500).json({ message: 'Error during login' });
  }
});

export default router;