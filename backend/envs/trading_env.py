import gymnasium as gym
from gymnasium import spaces
import numpy as np

class BitcoinTradingEnv(gym.Env):
    def __init__(self, df):
        super(BitcoinTradingEnv, self).__init__()
        self.df = df
        
        # Features calculadas no Dojo
        self.features = df[['log_ret', 'rsi', 'rsi_slope', 'macd_diff', 'bb_pband', 'bb_width', 'dist_ema50', 'dist_ema200', 'atr_pct']].values
        self.closes = df['close'].values
        
        # Ações: 0 (Ficar de fora/Fechar), 1 (Long), 2 (Short)
        self.action_space = spaces.Discrete(3) 
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(self.features.shape[1],), dtype=np.float32)
        
        self.current_step = 0
        self.position = 0
        self.entry_price = 0.0
        
        # 🛡️ GESTÃO DE RISCO INSTITUCIONAL (PAYOFF 1:2)
        self.fee = 0.0005          # Taxa da corretora
        self.stop_loss = -0.010    # Punição máxima em -1%
        self.take_profit = 0.020   # Prêmio máximo em +2%
        
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.position = 0
        self.entry_price = 0.0
        return self.features[self.current_step], {}
        
    def step(self, action):
        self.current_step += 1
        done = self.current_step >= len(self.df) - 1
        
        reward = 0.0
        current_price = self.closes[self.current_step]
        target_pos = 1 if action == 1 else (-1 if action == 2 else 0)
        
        # 1. Punição leve por excesso de inatividade (estimula a buscar operações)
        if self.position == 0 and target_pos == 0:
            reward -= 0.0005
            
        # 2. O Cão de Guarda do Treinamento (Avalia SL e TP)
        if self.position != 0:
            change_pct = (current_price - self.entry_price) / self.entry_price
            unrealized_pct = change_pct if self.position == 1 else -change_pct
            
            if unrealized_pct <= self.stop_loss:
                reward -= 5.0 # ❌ CHOQUE FORTE: Bateu no Stop Loss!
                self.position = 0
                target_pos = 0
            elif unrealized_pct >= self.take_profit:
                reward += 10.0 # 🏆 BISCOITO GIGANTE: Bateu no Take Profit!
                self.position = 0
                target_pos = 0
            else:
                # Recompensa contínua por estar no caminho certo (incentiva a segurar a posição vencedora)
                reward += (unrealized_pct * 1.5)

        # 3. Execução de Ordens pela IA
        if target_pos != self.position:
            if self.position != 0:
                # Se a IA decidiu fechar a operação manualmente antes de bater no SL/TP
                change_pct = (current_price - self.entry_price) / self.entry_price
                pnl_pct = change_pct if self.position == 1 else -change_pct
                reward += (pnl_pct * 20.0) # Multiplicador para o lucro/prejuízo real capturado
                
            if target_pos != 0:
                self.entry_price = current_price
                reward -= (self.fee * 5) # Punição ampliada pela taxa (ensina a não fazer overtrading)
                
            self.position = target_pos
            
        obs = self.features[self.current_step]
        return obs, reward, done, False, {}