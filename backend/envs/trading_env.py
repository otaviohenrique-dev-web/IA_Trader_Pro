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
        
        # 🛡️ GESTÃO DE RISCO ALINHADA COM A PRODUÇÃO (server.py)
        self.fee = 0.0010          # Taxa corrigida para 0.1%
        self.stop_loss = -0.010    # Punição máxima em -1%
        
        # Memória interna da operação para o Trailing Stop
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
        target_pos = 1 if action == 1 else (-1 if action == 2 else 0)
        
        # 🎯 ARMADILHA 1 RESOLVIDA: Nenhuma punição por inatividade.
        # A IA tem permissão total para não operar e esperar o momento perfeito.
        
        # 🎯 ARMADILHA 3 RESOLVIDA: Desalinhamento Treino vs. Produção
        if self.position != 0:
            change_pct = (current_price - self.entry_price) / self.entry_price
            unrealized_pct = change_pct if self.position == 1 else -change_pct
            
            # Atualiza o pico de lucro da operação atual
            if unrealized_pct > self.max_profit_pct:
                self.max_profit_pct = unrealized_pct

            # Aplica EXATAMENTE as mesmas regras de Breakeven e Trailing Stop do backend
            dynamic_stop = self.stop_loss
            
            if self.max_profit_pct >= 0.015: 
                dynamic_stop = self.max_profit_pct - 0.006
            elif self.max_profit_pct >= 0.008:
                dynamic_stop = 0.002

            # O Cão de Guarda atua se o stop dinâmico for atingido
            if unrealized_pct <= dynamic_stop:
                target_pos = 0 # Força a IA a fechar a posição
                
        # 3. Execução de Ordens pela IA (Aqui o PnL é julgado)
        if target_pos != self.position:
            
            # FECHAMENTO DA OPERAÇÃO
            if self.position != 0:
                change_pct = (current_price - self.entry_price) / self.entry_price
                pnl_pct = change_pct if self.position == 1 else -change_pct
                
                # Descontando as taxas (entrada e saída)
                real_pnl = pnl_pct - (self.fee * 2)
                
                # 🎯 ARMADILHA 2 RESOLVIDA: Reward Hacking
                # A recompensa (+ ou -) só é entregue AQUI, quando o lucro ou prejuízo é REALIZADO.
                # Multiplicador alto (100.0) para que o Cérebro sinta fortemente o impacto da vitória ou derrota.
                reward += (real_pnl * 100.0) 
                
            # ABERTURA DA OPERAÇÃO
            if target_pos != 0:
                self.entry_price = current_price
                self.max_profit_pct = 0.0 # Reseta a memória para a nova trade
                
                # Pequena punição inicial pela taxa para inibir overtrading (ensina que abrir ordem custa caro)
                reward -= (self.fee * 5.0) 
                
            self.position = target_pos
            
        obs = self.features[self.current_step]
        return obs, reward, done, False, {}