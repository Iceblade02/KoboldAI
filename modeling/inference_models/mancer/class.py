import requests, json
from typing import List, Optional
import os

import utils
from logger import logger
from modeling.inference_model import (
    GenerationSettings,
    ModelCapabilities,
    GenerationMode,
)

from modeling.inference_models.api_handler import(
    model_backend as api_handler_model_backend,
    batch_api_call
)

from modeling.stoppers import Stoppers

model_backend_name = "Mancer"
model_backend_type = "Mancer" #This should be a generic name in case multiple model backends are compatible (think Hugging Face Custom and Basic Hugging Face)

class MancerAPIError(Exception):
    def __init__(self, error_type: str, error_message) -> None:
        super().__init__(f"{error_type}: {error_message}")


class model_backend(api_handler_model_backend):
    """InferenceModel for interfacing with Mancer's generation API."""
    
    def __init__(self):
        super().__init__()
        self.url = "https://neuro.mancer.tech/oai/v1/models" #Due to functionality elsewhere in the code, this needs to be like this. But the actual server is https://neuro.mancer.tech/oai/v1/completions
        self.serverurl = "https://neuro.mancer.tech/oai/v1/completions"
        self.source = "Mancer"

        self.pres_pen = 0
        self.freq_pen = 0

        self.post_token_hooks = [
            #PostTokenHooks.stream_tokens,
        ]

        self.stopper_hooks = [
            #Stoppers.core_stopper,
            #Stoppers.dynamic_wi_scanner,
            Stoppers.singleline_stopper,
            #Stoppers.chat_mode_stopper, #Implemented by checking chatmode var directly!
            #Stoppers.stop_sequence_stopper,
        ]

        self.capabilties = ModelCapabilities(
            #embedding_manipulation=True,
            #post_token_hooks=True,
            stopper_hooks=True,
            #post_token_probs=True,
        )
        #self._old_stopping_criteria = None

    def get_requested_parameters(self, model_name, model_path, menu_path, parameters = {}, loaded_parameters = {}):

        default_parameters = {'freq_pen': 0, 'pres_pen': 0}

        if loaded_parameters == {}:
            loaded_parameters = self.read_settings_from_file()

        for key in default_parameters:
            if key not in loaded_parameters:
                loaded_parameters[key] = default_parameters[key]

        self.source = model_name

        requested_parameters = super().get_requested_parameters(model_name, model_path, menu_path, parameters, loaded_parameters)
        requested_parameters.append({ #Could these two be in the regular settings menu somehow?
            "uitype": "slider",
            "unit": "float",
            "label": "Frequency Penalty",
            "id": "freq_pen",
            "min": -2.0,
            "max": 2.0,
            "step": 0.05,
            "default": loaded_parameters['freq_pen'],
            "tooltip": "(only some models) This setting aims to control the repetition of tokens based on how often they appear in the input. It tries to use less frequently those tokens that appear more in the input, proportional to how frequently they occur. Token penalty scales with the number of occurrences. Negative values will encourage token reuse.",
            "menu_path": "Configuration",
            "extra_classes": "",
            "refresh_model_inputs": False
        })
        requested_parameters.append({
            "uitype": "slider",
            "unit": "float",
            "label": "Presence Penalty",
            "id": "pres_pen",
            "min": -2.0,
            "max": 2.0,
            "step": 0.05,
            "default": loaded_parameters['pres_pen'],
            "tooltip": "(only some models) Adjusts how often the model repeats specific tokens already used in the input. Higher values make such repetition less likely, while negative values do the opposite. Token penalty does not scale with the number of occurrences. Negative values will encourage token reuse.",
            "menu_path": "Configuration",
            "extra_classes": "",
            "refresh_model_inputs": False
        })
        return requested_parameters
    
    def set_input_parameters(self, parameters):
        super().set_input_parameters(parameters)
        self.pres_pen = parameters['pres_pen']
        self.freq_pen = parameters['freq_pen']


    def _save_settings(self, settings={}):
        settings.update({
                        "pres_pen": self.pres_pen,
                        "freq_pen": self.freq_pen
                    })
        super()._save_settings(settings)
    
    def get_supported_gen_modes(self) -> List[GenerationMode]:
        return super().get_supported_gen_modes() + [
            GenerationMode.UNTIL_EOS
        ]
    
    def is_valid(self, model_name, model_path, menu_path):
        return model_name == "Mancer"
    
    def get_models(self):

        # Get list of models from Mancer
        logger.init("Mancer models", status="Retrieving")
        req = requests.get(
            self.url, 
            )
        if(req.status_code == 200):
            r = req.json()
            engines = r["data"]
            try:
                engines = [{"value": en["id"], "text": "{} ({})".format(en['id'], "Ready")} for en in engines]
            except:
                logger.error(engines)
                raise
            
            online_model = ""

                
            logger.init_ok("Mancer Models", status="OK")
            logger.debug("Mancer Models: {}".format(engines))
            return engines
        else:
            # Something went wrong, print the message and quit since we can't initialize an engine
            logger.init_err("Mancer Models", status="Failed")
            logger.error(req.json())
            emit('from_server', {'cmd': 'errmsg', 'data': req.json()})
            return []
    
    def _raw_api_generate(
        self,
        prompt_plaintext: str,
        max_new: int,
        gen_settings: GenerationSettings,
        batch_count: Optional[int] = 1,
        do_streaming: Optional[bool] = False,
        is_core: Optional[bool] = False,
        seed: Optional[int] = None,
        chatmode: Optional[bool] = False,
        gen_mode: Optional[GenerationMode] = GenerationMode.STANDARD,
        **kwargs,
    ) -> List:

        # Store context in memory to use it for comparison with generated content
        utils.koboldai_vars.lastctx = prompt_plaintext

        if is_core & utils.koboldai_vars.chatmode: #TODO: Improve chat mode, mancer permits sending "user" and "bot" names in addition to the messages
            promptormessage = "messages"
            payload = [{"role": "user", "content": prompt_plaintext}]

        else:
            promptormessage = "prompt"
            payload = prompt_plaintext

        reqdata = {
            promptormessage: payload,
            'model': self.model_name,

            # TODO: Implement streaming
            'stream': False,

            'max_tokens': max_new,
            #TODO:Implement min tokens better
            'min_tokens': 10 if max_new > 10 else 0,
            'temperature': gen_settings.temp,
            'repetition_penalty': gen_settings.rep_pen,
            'presence_penalty': utils.koboldai_vars.pres_pen,
            'frequency_penalty': utils.koboldai_vars.freq_pen,
            'top_k': gen_settings.top_k,
            'top_a': gen_settings.top_a,
            'top_p': gen_settings.top_p,

            #TODO: Lots of other settings
            "typical_p": 1,
            "eta_cutoff": 0,
            "tfs": gen_settings.tfs,
            "mirostat_mode": 0,
            "mirostat_tau": 0,
            "mirostat_eta": 0,
            "logit_bias": None,
            "ignore_eos": False,

            "stop": self.plaintext_stoppers,

            #TODO: Lots of other settings
            "custom_token_bans": [],
            "stream": False,
            "timeout": None,
            "allow_logging": None,
            "logprobs": False,
            "top_logprobs": None
            
        }
        headers = {
            'accept': 'application/json',
            'Authorization': 'Bearer '+self.key,
            'Content-Type': 'application/json'
            }

        url=self.serverurl
        
        call={"url": url, "reqdata": reqdata, "headers": headers}

        items=batch_api_call(call, batch_count) #Call the API with the batch of requests

        outputs=[]
        for item in items: #Strip the outer layer of the response, and append the inner layer to the outputs list
            outputs.append(item["choices"][0]["text"]) #We now have a list of the texts [{"textA"}, {"textB"}, {"textC"} etc.]

        return outputs