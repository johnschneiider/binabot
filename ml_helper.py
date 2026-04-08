"""
Shared ML class definitions for pickling compatibility.
Both train_ml.py and binance_bot_django.py import from here,
so joblib.load() finds the classes under 'ml_helper.*' in both contexts.
"""
import numpy as np
from sklearn.isotonic import IsotonicRegression


class IsotonicCalibrated:
    """Wraps a fitted model with isotonic calibration on hold-out probabilities."""
    def __init__(self, base_model):
        self.base_model = base_model
        self._ir = None

    def fit(self, X_val, y_val):
        raw = self.base_model.predict_proba(X_val)[:, 1]
        self._ir = IsotonicRegression(out_of_bounds="clip")
        self._ir.fit(raw, y_val)
        return self

    def predict_proba(self, X):
        raw = self.base_model.predict_proba(X)[:, 1]
        cal = self._ir.predict(raw)
        return np.column_stack([1 - cal, cal])


class EnsembleModel:
    """Averages probabilities from two calibrated models, weighted by AUC."""
    def __init__(self, model_a, model_b, weight_a: float = 0.5):
        self.model_a  = model_a
        self.model_b  = model_b
        self.weight_a = weight_a
        self.weight_b = 1.0 - weight_a

    def predict_proba(self, X):
        pa  = self.model_a.predict_proba(X)[:, 1]
        pb  = self.model_b.predict_proba(X)[:, 1]
        avg = np.clip(self.weight_a * pa + self.weight_b * pb, 0.0, 1.0)
        return np.column_stack([1 - avg, avg])
