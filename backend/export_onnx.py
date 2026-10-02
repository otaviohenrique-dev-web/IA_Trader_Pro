"""
Exporta um modelo RecurrentPPO (.zip) para ONNX.

Diferença crucial em relação à versão antiga: o grafo agora DEVOLVE também o novo
estado da LSTM (h, c). Antes só saía o logit, então em produção/backtest a memória
da rede era sempre zerada, ao contrário do que acontecia no treino.

Uso:  python export_onnx.py models/sniper_pro_gen_27.zip
"""
import os
import sys

import numpy as np
import torch

import features as F


class OnnxablePolicy(torch.nn.Module):
    def __init__(self, policy):
        super().__init__()
        self.policy = policy

    def forward(self, obs, lstm_states_h, lstm_states_c):
        feats = self.policy.features_extractor(obs)
        out, (h, c) = self.policy.lstm_actor(feats.unsqueeze(0), (lstm_states_h, lstm_states_c))
        latent_pi = self.policy.mlp_extractor.forward_actor(out.squeeze(0))
        return self.policy.action_net(latent_pi), h, c


def export(model, onnx_path: str, verify: bool = True) -> None:
    policy = model.policy.to("cpu").eval()
    wrapper = OnnxablePolicy(policy).eval()
    shape = policy.lstm_hidden_state_shape
    obs = torch.randn(1, F.OBS_DIM)
    h0, c0 = torch.zeros(shape), torch.zeros(shape)

    kwargs = dict(
        export_params=True, opset_version=15, do_constant_folding=True,
        input_names=["obs", "lstm_states_h", "lstm_states_c"],
        output_names=["logits", "lstm_h_out", "lstm_c_out"],
        dynamic_axes={"obs": {0: "batch"}, "lstm_states_h": {1: "batch"}, "lstm_states_c": {1: "batch"},
                      "logits": {0: "batch"}, "lstm_h_out": {1: "batch"}, "lstm_c_out": {1: "batch"}},
    )
    try:
        torch.onnx.export(wrapper, (obs, h0, c0), onnx_path, dynamo=False, **kwargs)
    except TypeError:  # torch antigo não conhece o parâmetro dynamo
        torch.onnx.export(wrapper, (obs, h0, c0), onnx_path, **kwargs)

    import onnx
    m = onnx.load(onnx_path)            # incorpora pesos externos num arquivo único
    onnx.checker.check_model(m)
    onnx.save(m, onnx_path)
    if os.path.exists(onnx_path + ".data"):
        os.remove(onnx_path + ".data")

    if verify:  # paridade numérica: ONNX x SB3 durante 20 passos encadeados
        import onnxruntime as ort
        sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        h, c = np.zeros(shape, np.float32), np.zeros(shape, np.float32)
        th, tc = torch.zeros(shape), torch.zeros(shape)
        worst = 0.0
        for _ in range(20):
            x = np.random.randn(1, F.OBS_DIM).astype(np.float32)
            lg, h, c = sess.run(None, {"obs": x, "lstm_states_h": h, "lstm_states_c": c})
            with torch.no_grad():
                ref, th, tc = wrapper(torch.from_numpy(x), th, tc)
            worst = max(worst, float(np.abs(lg - ref.numpy()).max()))
        assert worst < 1e-3, f"ONNX diverge do PyTorch (erro máx {worst})"
        print(f"✅ ONNX exportado e verificado (erro máx vs PyTorch: {worst:.2e}) -> {onnx_path}")


if __name__ == "__main__":
    from sb3_contrib import RecurrentPPO
    if len(sys.argv) < 2:
        sys.exit("uso: python export_onnx.py models/<modelo>.zip")
    zip_path = sys.argv[1]
    export(RecurrentPPO.load(zip_path, device="cpu"), os.path.splitext(zip_path)[0] + ".onnx")
