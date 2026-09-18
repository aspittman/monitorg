from adapters.ccexchange import CCExchange
from adapters.etf_enhancer import ETFEnhancer
from adapters.etf_enhancer_lt import ETFEnhancerLT
from adapters.momentum_master import MomentumMaster
from adapters.options_covered import OptionsCovered
from adapters.options_secured import OptionsSecured
from adapters.options_direct import OptionsDirect
from adapters.options_inverted import OptionsInverted

ADAPTERS = dict(ccexchange=CCExchange, ETFEnhancer=ETFEnhancer, ETFEnhancerLT=ETFEnhancerLT,
                momentum_master=MomentumMaster, options_covered=OptionsCovered,
                options_secured=OptionsSecured, options_direct=OptionsDirect, options_inverted=OptionsInverted)
