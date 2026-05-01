import pandas as pd
import numpy as np
import pandas_ta_classic as ta
import os
import torch
from sb3_contrib import RecurrentPPO
from envs.trading_env import BitcoinTradingEnv

# --- CONFIGURAÇÕES DO DOJO ---
DADOS_BAIXADOS = "data/mercado_real_20260313.csv"
MODELO_ATUAL = "models/sniper_pro_gen_6.zip" 
PASSOS_DE_TREINO = 10000 

def preparar_dados(caminho_csv):
    print("🧹 Engenharia de Features nos dados reais...")
    df = pd.read_csv(caminho_csv)
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['rsi_slope'] = df['rsi'].diff()
    
    macd = ta.macd(df['close'])
    macd_col = [c for c in macd.columns if c.startswith('MACDh') or c.startswith('MACDH')][0]
    df['macd_diff'] = macd[macd_col]
    
    bb = ta.bbands(df['close'], length=20, std=2)
    upper_col, lower_col, width_col = [c for c in bb.columns if c.startswith('BBU')][0], [c for c in bb.columns if c.startswith('BBL')][0], [c for c in bb.columns if c.startswith('BBB')][0]
    df['bb_pband'] = (df['close'] - bb[lower_col]) / (bb[upper_col] - bb[lower_col])
    df['bb_width'] = bb[width_col]
    
    df['ema50'] = ta.ema(df['close'], length=50)
    df['ema200'] = ta.ema(df['close'], length=200)
    df['dist_ema50'] = (df['close'] - df['ema50']) / df['ema50']
    df['dist_ema200'] = (df['close'] - df['ema200']) / df['ema200']
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['atr_pct'] = df['atr'] / df['close']
    
    return df.dropna().copy()

# 🚀 INJEÇÃO: CLASSE ENVOLUCRO (BYPASS ESTRUTURAL COMPLETO)
class OnnxablePolicy(torch.nn.Module):
    """
    Wrapper que desmembra a política de decisão do RecurrentPPO.
    Roteia tensores manualmente para contornar bifurcações dinâmicas (if/else) do código nativo.
    """
    def __init__(self, policy):
        super().__init__()
        self.policy = policy
        # Deixamos os gradientes ativos apenas para que o exportador ONNX 
        # aceite guardar os pesos físicos dentro do ficheiro.

    def forward(self, obs, lstm_states_h, lstm_states_c):
        # 🚀 O Bypass Estrutural: Acesso direto às camadas
        
        # Passo A (Extração): Converte a observação original nas features latentes
        features = self.policy.features_extractor(obs)
        
        # Passo B (Modelagem de Sequência): Adiciona a dimensão 'sequence length' (tamanho 1) para a LSTM
        features_seq = features.unsqueeze(0)
        
        # Passo C (Coração LSTM): Passa pelas camadas recorrentes do ator
        latent_lstm, _ = self.policy.lstm_actor(features_seq, (lstm_states_h, lstm_states_c))
        
        # Passo D (Decisão): Remove a dimensão de sequência e passa na rede de ação final
        latent_policy = latent_lstm.squeeze(0)
        action = self.policy.action_net(latent_policy)
        
        # Passo E (Retorno)
        return action

if __name__ == "__main__":
    print("🥋 BEM-VINDO AO DOJO DE TREINAMENTO INSTITUCIONAL 🥋")
    
    if not os.path.exists(DADOS_BAIXADOS):
        print(f"❌ Arquivo {DADOS_BAIXADOS} não encontrado. Exporte da Vercel primeiro!")
        exit()

    df_treino = preparar_dados(DADOS_BAIXADOS)
    env = BitcoinTradingEnv(df_treino)
    
    print(f"🧠 Carregando Cérebro Base: {MODELO_ATUAL}")
    model = RecurrentPPO.load(MODELO_ATUAL, env=env, device="cpu")
    
    print(f"🔥 Iniciando Treinamento com Gestão de Risco Ativada ({PASSOS_DE_TREINO} steps)...")
    model.learn(total_timesteps=PASSOS_DE_TREINO)
    
    # 1. MANUTENÇÃO DO CÉREBRO BASE (.zip)
    # ============================================================
    novo_nome_zip = "models/sniper_pro_gen_7.zip"
    model.save(novo_nome_zip)
    print(f"\n🏆 Treinamento Concluído! Cérebro de Evolução salvo: {novo_nome_zip}")
    
    # 2. PREPARAÇÃO DO MOLDE PARA EXPORTAÇÃO ONNX
    # ============================================================
    print("\n⚙️ ETAPA 2: Preparando modelo para exportação ONNX...")
    print("  → Etapa 2.1: Aplicando Bypass Estrutural na política de decisão...")
    
    # Cria o wrapper com a rota manual
    onnx_policy = OnnxablePolicy(model.policy)
    onnx_policy.eval()
    
    # 3. CRIAÇÃO DOS TENSORES FICTÍCIOS (DUMMY INPUTS)
    # ============================================================
    print("  → Etapa 2.2: Criando tensores fictícios para mapeamento...")
    
    # Observações: 9 features
    dummy_obs = torch.randn(1, 9, dtype=torch.float32)
    
    # Estados LSTM do RecurrentPPO
    lstm_shape = model.policy.lstm_hidden_state_shape
    dummy_lstm_states_h = torch.zeros(lstm_shape, dtype=torch.float32)
    dummy_lstm_states_c = torch.zeros(lstm_shape, dtype=torch.float32)
    
    # NOTA: dummy_episode_starts removido, não é mais necessário no bypass!
    novo_nome_onnx = "models/sniper_pro_gen_7.onnx"
    
    # 4. EXPORTAÇÃO PARA FORMATO ONNX (DIRETA E LIMPA)
    # ============================================================
    print("  → Etapa 2.3: Compilando e Exportando...")
    
    import warnings
    warnings.filterwarnings("ignore")
    
    try:
        # A Mágica: Sem JIT Trace, apenas a exportação direta da via expressa
        torch.onnx.export(
            onnx_policy,
            (dummy_obs, dummy_lstm_states_h, dummy_lstm_states_c),
            novo_nome_onnx,
            export_params=True,
            opset_version=17,
            do_constant_folding=True,
            input_names=["obs", "lstm_states_h", "lstm_states_c"],
            output_names=["action"],
            dynamic_axes={
                "obs": {0: "batch_size"},
                "lstm_states_h": {1: "batch_size"}, 
                "lstm_states_c": {1: "batch_size"},
                "action": {0: "batch_size"}
            },
            verbose=False
        )
        
        # 🚀 NOVO PASSO: A FUSÃO DOS PESOS (Single File Enforcer)
        print("  → Etapa 2.4: Fundindo arquitetura e pesos num ficheiro único...")
        import onnx
        
        # O onnx.load é inteligente: ele lê o .onnx e puxa automaticamente o .onnx.data da pasta
        modelo_fundido = onnx.load(novo_nome_onnx)
        
        # O onnx.save, por padrão, injeta TUDO de volta num único arquivo físico
        onnx.save(modelo_fundido, novo_nome_onnx)
        
        # O Lixeiro: Removemos o arquivo .data solto para não sujar o seu PC
        arquivo_data = novo_nome_onnx + ".data"
        if os.path.exists(arquivo_data):
            os.remove(arquivo_data)
            print("  → 🧹 Ficheiro .data fragmentado limpo com sucesso.")
        
        # Verificação Final (Agora medimos em KB para ser preciso)
        if os.path.exists(novo_nome_onnx):
            arquivo_size_kb = os.path.getsize(novo_nome_onnx) / 1024
            print(f"\n✅ Modelo ONNX blindado e exportado com SUCESSO ABSOLUTO!")
            print(f"   📁 Arquivo: {novo_nome_onnx}")
            print(f"   💾 Tamanho Total Fundido: {arquivo_size_kb:.2f} KB")
        else:
            raise FileNotFoundError("Arquivo ONNX não foi criado")
            
    except Exception as e:
        print(f"\n❌ Erro crítico na compilação: {e}")
        novo_nome_onnx = None
    
    # 5. RESUMO FINAL E INSTRUÇÕES DE DEPLOYMENT
    print("\n" + "="*70)
    print("📊 RESUMO DA SESSÃO DE TREINAMENTO - SAÍDA DUPLA")
    print("="*70)
    
    print("\n📁 ARQUIVOS GERADOS:")
    print(f"   1️⃣  {novo_nome_zip}")
    print(f"       └─ Cérebro Base (Evolução Local)")
    
    if novo_nome_onnx and os.path.exists(novo_nome_onnx):
        print(f"\n   2️⃣  {novo_nome_onnx}")
        print(f"       └─ ARTEFATO DE PRODUÇÃO ONNX ✅")
        
        print("\n🚀 INSTRUÇÕES DE DEPLOYMENT (CRÍTICO):")
        print("   ┌─ Para o Dashboard na Vercel/Render:")
        print(f"   └─ Suba APENAS o arquivo: {novo_nome_onnx.split('/')[-1]}")
    else:
        print("\n   ⚠️  O Artefato ONNX Falhou.")
    
    print("\n" + "="*70)