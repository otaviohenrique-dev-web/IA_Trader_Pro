import gymnasium as gym
from gymnasium import spaces
import numpy as np

class BitcoinTradingEnv(gym.Env):
    def __init__(self, df):
        super(BitcoinTradingEnv, self).__init__()
        self.df = df
        
        # Features calculadas no Dojo (Note o índice do atr_pct para uso posterior)
        # 0:log_ret, 1:rsi, 2:rsi_slope, 3:macd_diff, 4:bb_pband, 5:bb_width, 6:dist_ema50, 7:dist_ema200, 8:atr_pct
        self.features = df[['log_ret', 'rsi', 'rsi_slope', 'macd_diff', 'bb_pband', 'bb_width', 'dist_ema50', 'dist_ema200', 'atr_pct']].values
        self.closes = df['close'].values
        
        # Ações: 0 (Ficar de fora/Fechar), 1 (Long), 2 (Short)
        self.action_space = spaces.Discrete(3) 
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(self.features.shape[1],), dtype=np.float32)
        
        self.current_step = 0
        self.position = 0
        self.entry_price = 0.0
        
        self.fee = 0.0010 
        self.stop_loss = -0.010 
        self.max_profit_pct = 0.0
        
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.position = 0
        self.entry_price = 0.0
        self.max_profit_pct = 0.0
        return self.features[self.current_step], {}
        
    def step(self, action):
        self.current_step += 1
        done = self.current_step >= len(self.df) - 1
        
        reward = 0.0
        current_price = self.closes[self.current_step]
        current_atr_pct = self.features[self.current_step][8] # Índice 8 é o atr_pct
        
        target_pos = 1 if action == 1 else (-1 if action == 2 else 0)
        
        # 🎯 REWARD SHAPING 2.0: A ARTE DE FICAR LÍQUIDO
        # Se a IA escolher ficar de fora (target_pos == 0) e a volatilidade for baixa (< 0.15%), ela ganha um "biscoito".
        # Isso ensina a IA a AMAR a inatividade durante madrugadas e mercados laterais (Chop Market).
        if target_pos == 0 and current_atr_pct < 0.0015:
            reward += 0.05  # Pequeno prêmio contínuo por ter disciplina
        
        # 🎯 PUNIÇÃO POR IMPRUDÊNCIA: Se tentar abrir ordem no Chop Market
        elif target_pos != 0 and self.position == 0 and current_atr_pct < 0.0015:
            reward -= 0.5   # Punição severa (equivalente a 0.5% de perda)
        
        if self.position != 0:
            change_pct = (current_price - self.entry_price) / self.entry_price
            unrealized_pct = change_pct if self.position == 1 else -change_pct
            
            if unrealized_pct > self.max_profit_pct:
                self.max_profit_pct = unrealized_pct

            dynamic_stop = self.stop_loss
            
            if self.max_profit_pct >= 0.015: 
                dynamic_stop = self.max_profit_pct - 0.006
            elif self.max_profit_pct >= 0.008:
                dynamic_stop = 0.002

            if unrealized_pct <= dynamic_stop:
                target_pos = 0 
                
        # Execução de Ordens pela IA
        if target_pos != self.position:
            
            # FECHAMENTO DA OPERAÇÃO
            if self.position != 0:
                change_pct = (current_price - self.entry_price) / self.entry_price
                pnl_pct = change_pct if self.position == 1 else -change_pct
                real_pnl = pnl_pct - (self.fee * 2)
                
                # Se o fechamento resultar em lucro líquido, prêmio massivo. Se for loss, dor.
                reward += (real_pnl * 100.0) 
                
            # ABERTURA DA OPERAÇÃO
            if target_pos != 0:
                self.entry_price = current_price
                self.max_profit_pct = 0.0 
                
                # Punição inicial pela taxa (custo de entrada)
                reward -= (self.fee * 5.0) 
                
        self.position = target_pos
        
        obs = self.features[self.current_step]
        return obs, reward, done, False, {}