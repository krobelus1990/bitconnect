from random import shuffle, seed
from collections import defaultdict

import bittensor
import torch
from torch import nn
from tqdm.auto import tqdm
from torch.nn import CrossEntropyLoss
import torch.nn.functional as F

from commune.bittensor import BitModule


import torch
from torch import nn
from sentence_transformers import SentenceTransformer


class RankingLoss(nn.Module):
    def __init__(self):
        super(RankingLoss, self).__init__()

    def forward(self, x, y):
        print(self)
        loss = torch.mean((x - y) ** 2)
        return loss


class RankingModel(nn.Module):
    def __init__(self, num_endpoints: int):

        super().__init__()
        self.num_endpoints = num_endpoints

        self.transformer = SentenceTransformer(
            "sentence-transformers/all-distilroberta-v1"
        )

        # TODO match embedding dim to transformer
        self.embeddings = torch.nn.Embedding(
            num_embeddings=num_endpoints,
            embedding_dim=self.transformer.get_sentence_embedding_dimension(),
        )

    def forward(self, sequence):

        seq_embeddings = torch.tensor(self.transformer.encode(sequence))

        # (num_receptors, dim)
        endpoint_embeddings = self.embeddings(torch.arange(0, self.num_endpoints))
        endpoint_embeddings = torch.nn.functional.normalize(endpoint_embeddings, p=2, dim=1)

        # (batch_size, num_endpoints)
        sims = torch.matmul(seq_embeddings, endpoint_embeddings.T)
        sims = (sims + 1) / 2  # bound from (0, 1)

        return sims



class BenchmarkModule(BitModule):
    __file__ = __file__
    default_config_path = 'bittensor.benchmark'
    def __init__(self, config=None, **kwargs):
        BitModule.__init__(self, config=config, **kwargs)
    @property
    def debug(self):
        return self.config.get('debug', False)

    def load_state(self):
        bittensor.logger(debug=self.debug)
        self.load_dataset()
        self.load_model()
        self.load_optimizer()
        self.load_metric()

    def load_dataset(self, block_size=128, **kwargs):
        self.dataset = bittensor.dataset(block_size=128)
        self.tokenizer = self.dataset.tokenizer

    def load_model(self):
        model_config = self.config['metric']
        self.model = RankingModel(**model_config['params'])
        self.num_endpoints = self.model.num_endpoints
    
    def load_optimizer(self,**kwargs):
        optimizer_kwargs = dict(path='torch.optim.Adam', params=dict(lr=0.00032))
        optimizer_kwargs.update(kwargs)
        optimizer_kwargs.update(self.config.get('optimizer', {}))
        optim_class = self.import_object(default_kwargs['path'])
        self.optimizer = optim_class(self.model.parameters(),**optimizer_kwargs['params'])


    def load_metric(self, **kwargs):
        metric_config = self.config['metric']
        self.metric = RankingLoss(**metric_config['params'])

    def load_receptor_pool(self, **kwargs):

        receptor_kwargs = dict(max_worker_threads=64, max_active_receptors=512)
        receptor_kwargs.update(kwargs)
        receptor_kwargs.update(self.config('receptor_pool', {}))
        self.receptor_pool = bittensor.receptor_pool(**receptor_kwargs,wallet=self.wallet)



    @staticmethod
    def causal_lm_loss(labels, logits):
        batch_size = logits.shape[0]
        loss_fct = CrossEntropyLoss()

        losses = []
        for batch in range(batch_size):
            shift_logits = logits[batch, :-1, :].contiguous()
            shift_labels = labels[batch, 1:].contiguous()
            loss = loss_fct(shift_logits.view(-1, 50258), shift_labels.view(-1))
            losses.append(loss)
        return torch.tensor(losses)


    def get_endpoints(self, num_endpoints=None):
        if num_endpoints == None:
            num_endpoints =self.num_receptors
        endpoints =self.graph.endpoint_objs
        shuffle(endpoints)
        endpoints = endpoints[:self.num_receptors]
        return 

    # def get_loss_fn(self):
    #     return nn.CrossEntropyLoss()
    
    @property
    def synapses(self):
        default_synapses = ['bittensor.synapse.TextCausalLM']
        synapse_class_strings = self.config.get('synapses', default_synapses)
        return [self.import_module(s)() for s in synapse_class_strings]
        
    def run(self):

        loss_fn = nn.CrossEntropyLoss()
        print(f"Querying {len(endpoints)} endpoints")

        # https://github.com/huggingface/transformers/blob/v4.21.3/src/transformers/models/gptj/modeling_gptj.py#L847

        num_batches = 100
 
        for idx in range(num_batches):
            print("getting next batch of data")
            inputs = next(self.dataset)
            str_inputs = [self.tokenizer.decode(s) for s in inputs]
            print(f"Querying endpoints")
            endpoints = self.get_endpoints()
            results = self.receptor_pool.forward(endpoints, synapses=self.synapses, inputs=[inputs] * x, timeout=20)
            tensors = []
            for tensor in results[0]:
                tensors.append(tensor[0])

            codes = []
            codes_count = defaultdict(int)
            for code in results[1]:
                code = code[0]
                codes.append(code)
                codes_count[code] += 1
            for code in sorted(set(codes)):
                print(f"{code}: {codes_count[code]}")
            print()

            print("Calculating losses for each endpoint")
            all_losses = []
            for _, logits in tqdm(enumerate(tensors)):
                all_losses.append(self.causal_lm_loss(inputs, logits))

            all_losses_tensor = torch.vstack(all_losses).T  # (batch_size, num_endpoints)
            inv_loss_tensor = 1/all_losses_tensor


            print("Model forward")
            sims = self.model(str_inputs)

            print("model backwards")

            ideal_rankings = torch.argsort(all_losses_tensor, axis=1)
            model_rankings = torch.argsort(sims, axis=1)

            loss = loss_fn(sims, inv_loss_tensor)
            #ndcg = metrics.ndcg_score(ideal_rankings, model_rankings)
            print(f"step: {idx} | loss={loss.item():.3f}")

            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()

if __name__ == '__name__':
    module = BenchmarkModule.deploy(actor=False)
    st.write(module)
    