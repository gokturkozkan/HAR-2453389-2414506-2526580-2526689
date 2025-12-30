import sqlite3 from 'sqlite3';
import { promisify } from 'util';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { User, EspDevice } from './types/index';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = process.env.DB_PATH || path.join(__dirname, '../har.db');

let db: sqlite3.Database;

export const initializeDatabase = (): Promise<void> => {
  return new Promise((resolve, reject) => {
    db = new sqlite3.Database(dbPath, (err) => {
      if (err) {
        reject(err);
        return;
      }

      // Create users table
      db.run(
        `CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY,
          username TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )`,
        (err) => {
          if (err) reject(err);
        }
      );

      // Create ESP devices table
      db.run(
        `CREATE TABLE IF NOT EXISTS esp_devices (
          id INTEGER PRIMARY KEY,
          is_connected BOOLEAN DEFAULT 0
        )`,
        (err) => {
          if (err) reject(err);
          else {
            Promise.all([seedMockUnityImages(), seedLabelsTable()])
              .then(() => resolve())
              .catch(reject);
          }
        }
      );
    });
  });
};

// Seed mock Unity images into DB if not already present
const seedMockUnityImages = async (): Promise<void> => {
  const imagesDir = path.join(__dirname, 'mock-Unity');
  const files = ['jumping.png', 'sitting.png', 'standing.png'];

  // Create table if missing
  await dbRun(
    `CREATE TABLE IF NOT EXISTS unity_images (
      name TEXT PRIMARY KEY,
      data BLOB NOT NULL
    )`
  );

  for (const file of files) {
    const filePath = path.join(imagesDir, file);
    if (!fs.existsSync(filePath)) continue;

    const existing = await dbGet('SELECT name FROM unity_images WHERE name = ?', [file]);
    if (existing) continue;

    const buffer = fs.readFileSync(filePath);
    await dbRun('INSERT INTO unity_images (name, data) VALUES (?, ?)', [file, buffer]);
  }
};

// Seed labels table with a single default label "sitting" if empty
const seedLabelsTable = async (): Promise<void> => {
  await dbRun(
    `CREATE TABLE IF NOT EXISTS labels (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE
    )`
  );

  const existing = await dbGet('SELECT name FROM labels LIMIT 1');
  if (!existing) {
    await dbRun('INSERT INTO labels (name) VALUES (?)', ['sitting']);
  }
};

export const getDatabase = (): sqlite3.Database => {
  if (!db) {
    throw new Error('Database not initialized');
  }
  return db;
};

// Database query helpers
export const dbRun = (sql: string, params: any[] = []): Promise<any> => {
  return new Promise((resolve, reject) => {
    getDatabase().run(sql, params, function (err) {
      if (err) reject(err);
      else resolve({ lastID: this.lastID, changes: this.changes });
    });
  });
};

export const dbGet = (sql: string, params: any[] = []): Promise<any> => {
  return new Promise((resolve, reject) => {
    getDatabase().get(sql, params, (err, row) => {
      if (err) reject(err);
      else resolve(row);
    });
  });
};

export const dbAll = (sql: string, params: any[] = []): Promise<any[]> => {
  return new Promise((resolve, reject) => {
    getDatabase().all(sql, params, (err, rows) => {
      if (err) reject(err);
      else resolve(rows || []);
    });
  });
};

export const closeDatabase = (): Promise<void> => {
  return new Promise((resolve, reject) => {
    if (db) {
      db.close((err) => {
        if (err) reject(err);
        else resolve();
      });
    } else {
      resolve();
    }
  });
};
