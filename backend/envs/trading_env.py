import gymnasium as gym
from gymnasium import spaces
import numpy as np

class BitcoinTradingEnv(gym.Env):
    def __init__(self, df):
        super(BitcoinTradingEnv, self).__init__()
        self.df = df
        
        # Features com MTF (Trend de 1h será injetada aqui no futuro)
        self.features = df[['log_ret', 'rsi', 'rsi_slope', 'macd_diff', 'bb_pband', 'bb_width', 'dist_ema50', 'dist_ema200', 'atr_pct']].values
        self.closes = df['close'].values
        
        self.action_space = spaces.Discrete(3) 
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(self.features.shape[1],), dtype=np.float32)
        
        self.reset_vars()
        self.fee = 0.0005  # 🛡️ SOLUÇÃO 3: Simulação de Taxa "Maker" (0.05%) para incentivar ordens limit
        self.stop_loss = -0.010 
        
    def reset_vars(self):
        self.current_step = 0
        self.position = 0
        self.entry_price = 0.0
        self.max_profit_pct = 0.0
        self.trade_duration = 0 # Memória de tempo do trade

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.reset_vars()
        return self.features[self.current_step], {}
        
    def step(self, action):
        self.current_step += 1
        done = self.current_step >= len(self.df) - 1
        reward = 0.0
        current_price = self.closes[self.current_step]
        current_atr_pct = self.features[self.current_step][8]
        
        target_pos = 1 if action == 1 else (-1 if action == 2 else 0)

        # 1. Incentivo à Liquidez em Baixa Volatilidade
        if target_pos == 0 and current_atr_pct < 0.0015:
            reward += 0.1 # Prêmio por paciência
        
        # 2. Gestão de Risco (Trailing Stop & Breakeven)
        if self.position != 0:
            self.trade_duration += 1
            change_pct = (current_price - self.entry_price) / self.entry_price
            unrealized_pct = change_pct if self.position == 1 else -change_pct
            self.max_profit_pct = max(self.max_profit_pct, unrealized_pct)

            dynamic_stop = self.stop_loss
            if self.max_profit_pct >= 0.015: dynamic_stop = self.max_profit_pct - 0.006
            elif self.max_profit_pct >= 0.008: dynamic_stop = 0.002

            if unrealized_pct <= dynamic_stop:
                target_pos = 0 

        # 3. Execução e Recompensas Reais
        if target_pos != self.position:
            if self.position != 0: # FECHAMENTO
                change_pct = (current_price - self.entry_price) / self.entry_price
                pnl_pct = change_pct if self.position == 1 else -change_pct
                real_pnl = pnl_pct - (self.fee * 2)
                
                # 🎯 SOLUÇÃO 1: Multiplicador de Risco/Retorno
                if real_pnl > 0:
                    reward += (real_pnl * 150.0) # Bônus agressivo para lucros
                    if self.trade_duration > 2: reward += 0.5 # Bônus por "segurar o vencedor"
                else:
                    reward += (real_pnl * 200.0) # Punição severa para perdas (aprende a cortar rápido)
                
            if target_pos != 0: # ABERTURA
                self.entry_price = current_price
                self.max_profit_pct = 0.0
                self.trade_duration = 0
                reward -= (self.fee * 10.0) # Custo de entrada alto para inibir entradas bobas

        self.position = target_pos
        return self.features[self.current_step], reward, done, False, {}