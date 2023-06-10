import optax
from jax import jit, value_and_grad, random, vmap
import jax.numpy as jnp
from jax.tree_util import tree_flatten, tree_unflatten, tree_map
from jaxtyping import Array, PyTree
from typing import Callable, Any 
from flax import linen as nn
from flax.linen.module import _freeze_attr
from .surrogates import _standardise

def train_surrogate(
        x: list[PyTree],
        y: PyTree,
        model: nn.Module,
        loss: Callable[[Array, Array], float],
        key: Any,
        epochs: int = 100,
        batch_size: int = 100,
        learning_rate: float = .001
    ) -> PyTree:
    """train_surrogate.
    
    Train a surrogate module on samples x and y

    :param x: Function parameter samples
    :type x: list[PyTree]
    :param y: Function outputs
    :type y: Array
    :param loss: Loss function for training
    :type loss: Callable[[Array, Array], float]
    :rtype: nn.Module
    """
    x = _freeze_attr(x)
    params = model.init(key, tree_map(lambda x: x[0], x))

    tx = optax.adam(learning_rate=learning_rate)
    opt_state = tx.init(params)
    loss_grad_fn = value_and_grad(jit(
        lambda p, x, y: training_loss(model, p, loss, x, y)
    ))

    # standardise y for the loss function
    y = tree_map(_standardise, y, model.y_mean, model.y_std)

    x = batch_tree(x, batch_size)
    y = batch_tree(y, batch_size)
    n_batches = len(x)

    for i in range(epochs):
        key, key_i = random.split(key)

        for b in random.permutation(key_i, n_batches, independent=True):
            loss_val, grads = loss_grad_fn(
                params,
                x[b],
                y[b]
            )
            updates, opt_state = tx.update(grads, opt_state)
            params = optax.apply_updates(params, updates)

    return params

def batch_tree(tree: PyTree, batch_size: int) -> list[PyTree]:
    flattened, treedef = tree_flatten(tree)
    batched = [
        jnp.split(leaf, batch_size)
        for leaf in flattened
    ]
    return [
        tree_unflatten(treedef, batch)
        for batch in zip(*batched)
    ]

def training_loss(
    model: nn.Module,
    params: PyTree,
    loss: Callable[[PyTree, PyTree], float],
    x: PyTree,
    y: PyTree
    ) -> float:
    return jnp.mean(
        vmap(
            lambda x, y: nn_loss(model, params, loss, x, y),
            in_axes=[tree_map(lambda x: 0, x), tree_map(lambda x: 0, y)]
        )(
            x,
            y
        ),
        axis=0
    )

def nn_loss(
    model: nn.Module,
    params: PyTree,
    loss: Callable[[PyTree, PyTree], float],
    x: PyTree,
    y: PyTree
    ) -> float:
    y_hat = model.apply(
        params,
        x,
        method = lambda module, x: module.limiter(
            module.rec(module.nn(module.vec(module.std(x))))
        )
    )
    return loss(y, y_hat)
