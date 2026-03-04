import gymnasium as gym
from gymnasium import spaces
import numpy as np

class BitcoinTradingEnv(gym.Env):
    metadata = {'render.modes': ['human']}

    def __init__(self, df, initial_balance=1000, fee_rate=0.0005):
        super(BitcoinTradingEnv, self).__init__()
        self.df = df
        self.initial_balance = initial_balance
        self.fee_rate = fee_rate
        
        # 0=Neutro, 1=Long, 2=Short
        self.action_space = spaces.Discrete(3)

        # Features do arquivo PRO
        self.feature_cols = [
            'log_ret', 'rsi', 'rsi_slope', 'macd_diff', 
            'bb_pband', 'bb_width', 'dist_ema50', 
            'dist_ema200', 'atr_pct'
        ]
        
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(len(self.feature_cols),), dtype=np.float32
        )

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.balance = self.initial_balance
        self.position = 0  # 0=Neutro
        self.portfolio_value = self.initial_balance
        self.holding_steps = 0 # Contador de tempo na posição
        
        return self._next_observation(), {}

    def _next_observation(self):
        obs = self.df.iloc[self.current_step][self.feature_cols].values
        return obs.astype(np.float32)

    def step(self, action):
        target_position = 0
        if action == 1: target_position = 1
        elif action == 2: target_position = -1

        current_price = self.df.iloc[self.current_step]['close']
        next_step = self.current_step + 1
        
        if next_step >= len(self.df):
            return self._next_observation(), 0, True, False, {}

        next_price = self.df.iloc[next_step]['close']
        
        # --- CÁLCULO FINANCEIRO ---
        price_change_pct = (next_price - current_price) / current_price
        # Mantemos taxa baixa (0.0001) para ele não travar
        tx_cost = self.fee_rate if target_position != self.position else 0
        step_return = (self.position * price_change_pct) - tx_cost
        
        self.portfolio_value *= (1 + step_return)
        
        # --- SISTEMA DE RECOMPENSA "BÚSSOLA INTELIGENTE" ---
        
        # 1. Recompensa Pura pelo Lucro (Sem punição extra por drawdown)
        step_reward = step_return * 100
        
        # 2. A LEI DA TENDÊNCIA (EMA 200)
        # Usamos a feature 'dist_ema200' que já temos
        dist_ema200 = self.df.iloc[self.current_step]['dist_ema200']
        
        # Se Preço > EMA 200 (Tendência de Alta) E ele tenta SHORT
        if dist_ema200 > 0 and target_position == -1:
            step_reward -= 0.05 # Punição: "Não nade contra a maré!"
            
        # Se Preço < EMA 200 (Tendência de Baixa) E ele tenta LONG
        if dist_ema200 < 0 and target_position == 1:
            step_reward -= 0.05 # Punição: "Não pegue faca caindo!"

        # 3. Bônus por Seguir a Tendência (Incentivo Positivo)
        if (dist_ema200 > 0 and target_position == 1) or (dist_ema200 < 0 and target_position == -1):
            step_reward += 0.02

        # 4. Taxa de Inatividade SUAVE (Para ele não dormir, mas sem pânico)
        if self.position == 0:
            step_reward -= 0.005 

        # Atualiza Estado
        self.position = target_position
        self.current_step += 1
        
        if target_position != self.position:
            self.holding_steps = 0
        elif self.position != 0:
            self.holding_steps += 1
            
        terminated = False
        truncated = False
        
        if self.portfolio_value < self.initial_balance * 0.5:
            terminated = True
            step_reward = -10

        info = {'portfolio_value': self.portfolio_value, 'position': self.position}

        return self._next_observation(), step_reward, terminated, truncated, info