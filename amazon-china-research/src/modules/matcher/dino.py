"""DINOv2 特徴量マッチングモジュール

Meta AI の DINOv2 (ViT-Small/14, 22M params) を使用して、
画像の「意味的な類似度」を384次元ベクトルのコサイン類似度で計算する。

ORBが局所キーポイント比較（角度・背景変化に弱い）なのに対し、
DINOv2は画像全体のセマンティック特徴を捉え、
異なる角度・背景・照明でも同一商品を高精度で検出できる。

モデルサイズ: ~86MB (vits14)
推論速度: ~50ms/枚 (CPU)
特徴ベクトル: 384次元 L2正規化
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# 遅延シングルトン
_model = None
_transform = None
_load_attempted = False


def is_available() -> bool:
    """torch が import できるか"""
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def _ensure_model():
    """初回呼び出し時に dinov2_vits14 をロード (~86MB)"""
    global _model, _transform, _load_attempted

    if _model is not None:
        return True
    if _load_attempted:
        return False

    _load_attempted = True
    try:
        import torch
        from torchvision import transforms

        logger.info("DINOv2 モデルをロード中 (dinov2_vits14)...")
        _model = torch.hub.load(
            "facebookresearch/dinov2", "dinov2_vits14", pretrained=True
        )
        _model.eval()

        _transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ])

        logger.info("DINOv2 モデルロード完了")
        return True
    except Exception as e:
        logger.warning(f"DINOv2 モデルロード失敗: {e}")
        _model = None
        _transform = None
        return False


def extract_features(img_bytes: bytes) -> Optional[np.ndarray]:
    """画像バイト列から384次元L2正規化ベクトルを抽出

    Args:
        img_bytes: JPEG/PNG画像のバイト列

    Returns:
        384次元 float32 numpy配列（L2正規化済み）、失敗時はNone
    """
    if not _ensure_model():
        return None

    try:
        import torch
        from PIL import Image
        from io import BytesIO

        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        tensor = _transform(img).unsqueeze(0)  # [1, 3, 224, 224]

        with torch.no_grad():
            features = _model(tensor)  # [1, 384]

        feat = features[0].numpy().astype(np.float32)
        # L2正規化
        norm = np.linalg.norm(feat)
        if norm > 0:
            feat = feat / norm
        return feat
    except Exception as e:
        logger.warning(f"DINOv2 特徴量抽出失敗: {e}")
        return None


def cosine_similarity(feat1: np.ndarray, feat2: np.ndarray) -> float:
    """2つのL2正規化済み特徴ベクトルのコサイン類似度

    L2正規化済みなのでドット積 = コサイン類似度

    Returns:
        類似度 (0.0 - 1.0)
    """
    return float(np.dot(feat1, feat2).clip(0.0, 1.0))
