import glob
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

LABEL_MAP = {"idle": 0, "walk": 1, "sit": 2}


def make_windows(X, y, window_size, stride):
    Xw, yw = [], []
    n = len(X)
    for start in range(0, n - window_size + 1, stride):
        end = start + window_size
        x_win = X[start:end]
        y_win = y[start:end]
        labels, counts = np.unique(y_win, return_counts=True)
        y_label = labels[np.argmax(counts)]
        Xw.append(x_win)
        yw.append(y_label)
    return np.stack(Xw), np.array(yw)


class WindowsDataset(Dataset):
    def __init__(self, Xw, yw):
        self.X = torch.tensor(Xw, dtype=torch.float32)
        self.y = torch.tensor(yw, dtype=torch.long)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = self.X[idx].transpose(0, 1)
        return x, self.y[idx]


class CNN1D(nn.Module):
    def __init__(self, in_channels, num_classes):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(in_channels, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Conv1d(64, 128, kernel_size=5, padding=2),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, num_classes),
        )

    def forward(self, x):
        return self.net(x)


def train_one_epoch(model, loader, optimizer, criterion, device):
    model.train()
    total_loss, correct, total = 0.0, 0, 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        logits = model(x)
        loss = criterion(logits, y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * y.size(0)
        correct += (logits.argmax(dim=1) == y).sum().item()
        total += y.size(0)
    return total_loss / total, correct / total


@torch.no_grad()
def eval_one_epoch(model, loader, criterion, device):
    model.eval()
    total_loss, correct, total = 0.0, 0, 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        logits = model(x)
        loss = criterion(logits, y)
        total_loss += loss.item() * y.size(0)
        correct += (logits.argmax(dim=1) == y).sum().item()
        total += y.size(0)
    return total_loss / total, correct / total


def load_dataset_from_csv(folder="data"):
    files = sorted(glob.glob(f"{folder}/session_*.csv"))
    if not files:
        raise RuntimeError("No CSV files found in data/. Record data first.")

    X_list, y_list = [], []
    for fp in files:
        df = pd.read_csv(fp)
        feat_cols = [c for c in df.columns if c.startswith("n") and c.endswith(("_ax", "_ay", "_az", "_gx", "_gy", "_gz"))]
        X = df[feat_cols].to_numpy(dtype=np.float32)
        labels = df["label"].astype(str).str.strip().to_list()
        y = np.array([LABEL_MAP[l] for l in labels], dtype=np.int64)
        X_list.append(X)
        y_list.append(y)

    X_all = np.concatenate(X_list, axis=0)
    y_all = np.concatenate(y_list, axis=0)
    return X_all, y_all


def main():
    X, y = load_dataset_from_csv("data")

    fs = 3.57
    window_seconds = 10.0
    overlap = 0.5
    batch_size = 64
    epochs = 20

    window_size = int(round(window_seconds * fs))
    stride = int(round(window_size * (1.0 - overlap)))
    window_size = max(window_size, 8)
    stride = max(stride, 1)

    Xw, yw = make_windows(X, y, window_size, stride)

    mean = Xw.reshape(-1, Xw.shape[-1]).mean(axis=0)
    std = Xw.reshape(-1, Xw.shape[-1]).std(axis=0) + 1e-6
    Xw = (Xw - mean) / std

    num_classes = len(np.unique(y))
    counts = np.bincount(yw, minlength=num_classes)
    weights = 1.0 / (counts + 1e-6)
    weights = weights / weights.sum() * num_classes

    n = len(Xw)
    split = int(n * 0.8)
    X_train, y_train = Xw[:split], yw[:split]
    X_val, y_val = Xw[split:], yw[split:]

    train_ds = WindowsDataset(X_train, y_train)
    val_ds = WindowsDataset(X_val, y_val)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=False)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = CNN1D(in_channels=X.shape[1], num_classes=num_classes).to(device)

    class_weights = torch.tensor(weights, dtype=torch.float32).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)

    for ep in range(1, epochs + 1):
        tr_loss, tr_acc = train_one_epoch(model, train_loader, optimizer, criterion, device)
        va_loss, va_acc = eval_one_epoch(model, val_loader, criterion, device)
        print(f"Epoch {ep:02d} | train loss {tr_loss:.4f} acc {tr_acc:.3f} | val loss {va_loss:.4f} acc {va_acc:.3f}")

    torch.save(
        {
            "state_dict": model.state_dict(),
            "mean": mean,
            "std": std,
            "window_size": window_size,
            "stride": stride,
            "fs": fs,
            "label_map": LABEL_MAP,
            "in_channels": int(X.shape[1]),
            "num_classes": int(num_classes),
        },
        "cnn1d_bundle.pth",
    )
    print("Saved: cnn1d_bundle.pth")


if __name__ == "__main__":
    main()
