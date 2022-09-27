import torch
import torch.nn.functional as F
import numpy as np
import ABIDEParser as Reader
import argparse
import random
from torch_geometric.data import Data
from sklearn.model_selection import StratifiedKFold
from scipy.spatial import distance
from model_RGAT import RGAT
from sklearn.metrics import roc_auc_score #AUC

import igraph as ig



def main():
    parser = argparse.ArgumentParser(description='Graph CNNs for population graphs: '
                                                 'classification of the ABIDE dataset')
    parser.add_argument('--num_features', default=2000, type=int, help='Number of features to keep for '
                                                                       'the feature selection step (default: 2000)')
    parser.add_argument('--num_training', default=1.0, type=float, help='Percentage of training set used for '
                                                                        'training (default: 1.0)')
    parser.add_argument('--atlas', default='ho', help='atlas for network construction (node definition) (default: ho, '
                                                      'see preprocessed-connectomes-project.org/abide/Pipelines.html '
                                                      'for more options )')
    parser.add_argument('--connectivity', default='correlation', help='Type of connectivity used for network '
                                                                      'construction (default: correlation, '
                                                                      'options: correlation, partial correlation, '
                                                                      'tangent)')
    parser.add_argument('--folds', default=0, type=int, help='For cross validation, specifies which fold will be '
                                                            'used. All folds are used if set to 11 (default: 11)')

    args = parser.parse_args()
    #start_time = time.time()
    params = dict()
    params['num_features'] = args.num_features
    params['num_training'] = args.num_training
    atlas = args.atlas
    connectivity = args.connectivity
    ########################################################################

    #GAT参数
    #num_node_features, n_conv_layers, layer_size, n_class, dropout_p

    #layer_size=[12,7,2,2]
    #dropout_p=0.3
    # test_size = 0.3
    lr = 1e-3
    hid_c = 12
    n_epoch = 4000
    seed = 14


    #################################
    n_class = 2

    #start_time = time.time()

    np.random.seed(seed)  # for numpy
    random.seed(seed)
    torch.manual_seed(seed)  # for cpu/GPU
    torch.cuda.manual_seed(seed)  # for current GPU
    torch.cuda.manual_seed_all(seed)  # for all GPU
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.enabled = False
    torch.backends.cudnn.deterministic = True

    subject_IDs = Reader.get_ids()
    labels = Reader.get_subject_score(subject_IDs, score='DX_GROUP')
    sites = Reader.get_subject_score(subject_IDs, score='SITE_ID')
    unique = np.unique(list(sites.values())).tolist()

    num_classes = n_class
    num_nodes = len(subject_IDs)
    y_data = np.zeros([num_nodes, num_classes])
    y = np.zeros([num_nodes, 1])
    site = np.zeros([num_nodes, 1], dtype=np.int)

    for i in range(num_nodes):
        y_data[i, int(labels[subject_IDs[i]]) - 1] = 1
        y[i] = int(labels[subject_IDs[i]])
        site[i] = unique.index(sites[subject_IDs[i]])

    features = Reader.get_networks(subject_IDs, kind=connectivity, atlas_name=atlas)

    #train/test
    skf = StratifiedKFold(n_splits=10)
    cv_splits = list(skf.split(features, np.squeeze(y)))

    train_index = cv_splits[args.folds][0]
    test_index = cv_splits[args.folds][1]

    def sample_mask(idx, l):
        """Create mask."""
        mask = np.zeros(l)
        mask[idx] = 1
        return np.array(mask, dtype=np.bool)

    labeled_ind = Reader.site_percentage(train_index, params['num_training'], subject_IDs)

    features = Reader.feature_selection(features, y, labeled_ind, params['num_features'])
    print(f'features: {features}')
    print(f'features.shape: {features.shape}')

    adj = Reader.create_affinity_graph_from_scores(['SEX', 'SITE_ID'], subject_IDs)
    print(f'adj: {adj}')
    print(f'adj.shape: {adj.shape}')

    a = []
    b = []
    c = []
    for i in range(len(adj)):
        for j in range(len(adj)):
            if adj[i][j] != 0:
                a.append(i)
                b.append(j)
                c.append(adj[i][j])
    edge_index = torch.tensor([a, b], dtype=torch.long)
    edge_attr = torch.tensor(c, dtype=torch.float)
    x = torch.tensor(features, dtype=torch.float)
    y = torch.tensor(y-1, dtype=int)
    print(f'y: {y}')
    y = np.squeeze(y)

    data = Data(x=x, edge_index=edge_index, edge_attr=edge_attr, y=y)
    data.num_classes = num_classes
    data.train_mask = sample_mask(train_index, data.num_nodes)
    data.test_mask = sample_mask(test_index, data.num_nodes)

    #
    print(f'edge_attr: {data.edge_attr}')
    print(f'x: {data.x}')
    edge = []
    edge_attr = data.edge_attr.tolist()
    for i in range(data.num_edges):
        e = []
        e.append(edge_attr[i])
        edge.append(e)
    edge = torch.tensor(edge, dtype=torch.float)
    print(f'edge: {edge}')  # 边权

    print(f'Number of nodes: {data.num_nodes}')
    print(f'Number of edges: {data.num_edges}')
    print(f'y: {data.y}')  # y
    print(f'edge_index: {data.edge_index}')
    print(f'edge_index[0]: {data.edge_index[0]}')
    print(f'labels: {labels}')  #
    print(f'data.num_classes: {data.num_classes}')
    print(f'Number of node features: {data.num_node_features}')
    print(f'Number of node features: {data.num_features}')
    print(f'Number of edge features: {data.num_edge_features}')
    print(f'Average node degree: {data.num_edges / data.num_nodes:.2f}')
    print(f'if edge indices are ordered and do not contain duplicate entries.: {data.is_coalesced()}')
    print(f'Number of training nodes: {data.train_mask.sum()}')
    print(f'Number of testing nodes: {data.test_mask.sum()}')  #test
    print(f'Training node label rate: {int(data.train_mask.sum()) / data.num_nodes:.2f}')
    print(f'Contains isolated nodes: {data.contains_isolated_nodes()}')
    print(f'Contains self-loops: {data.contains_self_loops()}')
    print(f'Is undirected: {data.is_undirected()}')

    my_net = RGAT(in_c=data.num_node_features, hid_c=hid_c, out_c=n_class)

    #################################################################

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    my_net = my_net.to(device)
    data = data.to(device)
    edge = edge.to(device)

    optimizer = torch.optim.Adam(my_net.parameters(), lr=lr)


    my_net.train()
    for epoch in range(n_epoch):
        optimizer.zero_grad()

        output = my_net(data, edge)
        loss = F.nll_loss(output[data.train_mask], data.y[data.train_mask])
        loss.backward()
        optimizer.step()

        print("Epoch", epoch + 1, "Loss", loss.item())


    my_net.eval()
    _, prediction = my_net(data, edge).max(dim=1)


    targ = data.y
    print(f'prediction[data.test_mask]p: {prediction[data.test_mask]}')
    print(f'targ[data.test_mask]: {targ[data.test_mask]}')

    test_correct = prediction[data.test_mask].eq(targ[data.test_mask]).sum().item()
    test_num = data.test_mask.sum().item()

    print("Accuracy of Test Samples: ", test_correct / test_num)

    y_test = targ[data.test_mask].data.cpu().numpy()
    y_pred = prediction[data.test_mask].data.cpu().numpy()
    auc_score = roc_auc_score(y_test, y_pred)
    print("AUC of Test Samples: ", auc_score)

    #######################################################

    num_nodes_of_interest = 2
    head_to_visualize = 0
    # 选择要绘制的目标节点（随机节点）
    nodes_of_interest_ids = np.random.randint(low=0, high=data.num_nodes, size=num_nodes_of_interest)

    put_x1 = my_net.conv1.forward(x=data.x, edge_index=data.edge_index, edge_value=edge,
                                  return_attention_weights=True)[1]
    print(f'put_x1 = {put_x1}')
    edge_index = put_x1[0]
    edge_index = np.squeeze(edge_index)
    edge_index = edge_index.cpu()
    print(f'edge_index = {edge_index}')
    all_attention_weights = put_x1[1]
    all_attention_weights = all_attention_weights.cpu().detach()
    all_attention_weights = np.squeeze(all_attention_weights)
    print(f'all_attention_weights = {all_attention_weights}')
    print(all_attention_weights.shape)

    target_node_ids = edge_index[0]
    source_nodes = edge_index[1]

    for target_node_id in nodes_of_interest_ids:
        # Step 1: Find the neighboring nodes to the target node
        # Note: self edges are included so the target node is it's own neighbor (Alexandro yo soy tu madre)
        src_nodes_indices = torch.eq(target_node_ids, target_node_id)
        source_node_ids = source_nodes[src_nodes_indices].cpu().numpy()
        size_of_neighborhood = len(source_node_ids)

        # Step 2: Fetch their labels
        labels = data.y[source_node_ids].cpu().numpy()

        # Step3
        attention_weights = all_attention_weights[src_nodes_indices].cpu().numpy()

        print(f'Max attention weight = {np.max(attention_weights)} and min = {np.min(attention_weights)}')
        attention_weights /= np.max(attention_weights)

        # Build up the neighborhood graph whose attention we want to visualize
        # igraph constraint - it works with contiguous range of ids so we map e.g. node 497 to 0, 12 to 1, etc.
        id_to_igraph_id = dict(zip(source_node_ids, range(len(source_node_ids))))
        ig_graph = ig.Graph()
        ig_graph.add_vertices(size_of_neighborhood)
        ig_graph.add_edges(
            [(id_to_igraph_id[neighbor], id_to_igraph_id[target_node_id]) for neighbor in source_node_ids])

        # Prepare the visualization settings dictionary and plot
        visual_style = {
            "edge_width": attention_weights,
            "layout": ig_graph.layout_reingold_tilford_circular()
        }

        color_map = ['red', 'blue']
        visual_style["vertex_color"] = [color_map[label] for label in labels]

        ig.plot(ig_graph, **visual_style)


if __name__ == '__main__':
    main()