from sideinfo_release import *
import matplotlib.pyplot as plt
import numpy as np
import timeit
import sys
import argparse
import os


then = timeit.default_timer()

parser = argparse.ArgumentParser()
parser.add_argument('--data', type=str, default = '',  help='data path')
parser.add_argument('--dim', type=int, default = 1,  help='dimension of data')
parser.add_argument('--init', type=int, default = 5,  help='number of inits')
parser.add_argument('--out', type=str, default = 'test',  help='output_directory')
parser.add_argument('--prefix', type=str, default = 'http://localhost:8888/files',  help='url prefix')
parser.add_argument('--alpha', type=float, default = 0.05,  help='fdr')
parser.add_argument('--intensity', type=float, default = 1,  help='fdr')
parser.add_argument('--fdr_scale', type=float, default = 1,  help='fd scale')
parser.add_argument('--mirror', type=float, default = 1,  help='mirror')
parser.add_argument('--cuda', action='store_true', help='use cuda')


opt = parser.parse_args()
print (opt)

fn = opt.data
dim = opt.dim

out_dir = opt.out
if not os.path.exists(out_dir):
    os.makedirs(out_dir)

data = np.loadtxt(open(fn, "rb"), delimiter=",", skiprows=1)
x = data[:,0:dim]
p = data[:,dim]
h = data[:,dim+1]
n_samples = len(x)

grids = None
x_prob = None

if dim == 1:
    max_x = np.max(x)
    min_x = np.min(x)
    x_prob = np.arange(min_x, max_x, (max_x - min_x)/1000.0)
    x_prob = x_prob.reshape((len(x_prob), 1))
    x_prob = Variable(torch.from_numpy(x_prob.astype(np.float32)))

elif dim == 2:
    max_x0 = np.max(x[:,0])
    min_x0 = np.min(x[:,0])
    max_x1 = np.max(x[:,1])
    min_x1 = np.min(x[:,1])
    x_prob0 = np.arange(min_x0, max_x0, (max_x0 - min_x0)/100.0)
    x_prob1 = np.arange(min_x1, max_x1, (max_x1 - min_x1)/100.0)
    X_grid, Y_grid = np.meshgrid(x_prob0, x_prob1)
    x_prob = Variable(torch.from_numpy(
    np.concatenate([[X_grid.flatten()], [Y_grid.flatten()]]).T.astype(np.float32)))
    grids = (X_grid, Y_grid)


if not x_prob is None:
    print(x_prob.size())
    if opt.cuda:
        x_prob = x_prob.cuda()

#network = get_network(cuda = True, dim = dim)
#optimizer = optim.Adagrad(network.parameters(), lr = 0.01)

bhp = BH(p, alpha = opt.alpha)[1]
lambda_param = 4/bhp
print('lambda ', lambda_param)

#from IPython import embed; embed()

#select = np.logical_or(p < bhp * 10, p > 1 - bhp * 10)
#x = x[select, :]
#p = p[select]

indices = np.random.permutation(x.shape[0])
A = [indices[:x.shape[0]/3], indices[x.shape[0]/3 : x.shape[0]/3*2], indices[x.shape[0]/3 * 2:]]
train = A
val = [A[1], A[2], A[0]]
test = [A[2], A[0], A[1]]
outputs = []
preds = []
gts = []

info = {}
info['filename'] = fn.replace('_', '\_')

loss_hists1 = []
loss_hists2 = []

efdr = np.zeros((3,3))
scales = np.zeros(3)

ninit = opt.init



if dim == 1:
    x = x.reshape((x.shape[0], 1))

for i in range(3):
    networks = []
    scores = []
    loss_hist1_array = []
    loss_hist2_array = []
    for j in range(ninit):
        network = get_network(num_layers = 10, cuda = opt.cuda, dim = dim, scale = opt.mirror)
        optimizer = optim.Adagrad(network.parameters(), lr = 0.01)
        train_idx = train[i]
        val_idx = val[i]
        test_idx = test[i]

        #network init
        try:
            p_target = opt_threshold_multi(x[train_idx,:], p[train_idx], 10, alpha = opt.alpha)
        except:
            p_target = np.ones(x[train_idx,:].shape[0]) * Storey_BH(p[train_idx], alpha = opt.alpha)[1]


        #plt.figure()
        #plt.scatter(x, p_target)
        loss_hist = train_network_to_target_p(network, optimizer, x[train_idx,:], p_target, num_it = 3000, cuda= opt.cuda, dim = dim)
        loss_hist2, s, s2 = train_network(network, optimizer, x[train_idx,:], p[train_idx], num_it = 6000, cuda = opt.cuda, dim = dim, alpha = opt.alpha, lambda2_ = lambda_param, fdr_scale = opt.fdr_scale)

        loss_hist_np = np.array(loss_hist2)
        score = np.mean(loss_hist_np[-100:])
        print(j,score)
        networks.append(network)
        scores.append(score)
        loss_hist1_array.append(loss_hist)
        loss_hist2_array.append(loss_hist2)

    idx = np.argmin(np.array(scores))
    print idx

    loss_hist = loss_hist1_array[idx]
    loss_hist2 = loss_hist2_array[idx]
    network = networks[idx]

    loss_hists1.append(loss_hist)
    loss_hists2.append(loss_hist2)

    scale, efdr[i,1] = get_scale(network, x[val_idx,:], p[val_idx], cuda = opt.cuda, lambda2_ = 5e12, fit = True, dim = dim, alpha = opt.alpha, fdr_scale = opt.fdr_scale, mirror = opt.mirror)
    _, efdr[i,2] = get_scale(network, x[test_idx,:], p[test_idx], cuda = opt.cuda, lambda2_ = 5e12, scale = scale, dim = dim, alpha = opt.alpha, fdr_scale = opt.fdr_scale, mirror = opt.mirror)
    _, efdr[i,0] = get_scale(network, x[train_idx,:], p[train_idx], cuda = opt.cuda, lambda2_ = 5e12, scale = scale, dim = dim, alpha = opt.alpha, fdr_scale = opt.fdr_scale, mirror = opt.mirror)

    scales[i] = scale
    if scale > 2 or scale < 0.5:
        print('Warning: abnormal scale factor, suggest rerun')

    n_samples = len(x[test_idx])
    x_input = Variable(torch.from_numpy(x[test_idx,:].astype(np.float32).reshape(n_samples ,dim)))
    p_input = Variable(torch.from_numpy(p[test_idx].astype(np.float32).reshape(n_samples ,1)))
    if opt.cuda:
        x_input = x_input.cuda()
        p_input = p_input.cuda()
    
    output = network.forward(x_input) * scale
    pred = (p_input < output).cpu().data.numpy()
    pred = pred[:,0].astype(np.float32)
    preds.append(pred)

    if not x_prob is None:
        outputs.append(network.forward(x_prob) * scale)

    gts.append(h[test_idx])
    torch.save(network.state_dict(), opt.out + '/model_{}.th'.format(i))


preds = np.concatenate(preds)
gts = np.concatenate(gts)

print sum(gts)
print sum(preds)
print sum(preds * gts)
print 1 - sum(preds * gts)/sum(preds)

info['number of ground truth discoveries'] = sum(gts)
info['number of discoveries'] = sum(preds)
info['set FDR'] = opt.alpha
info['actual FDR'] = 1 - sum(preds * gts)/sum(preds)
info['BH result'] = BH(p, alpha = opt.alpha)
info['Storey BH result'] = Storey_BH(p, alpha = opt.alpha)
info['elapsed time'] = timeit.default_timer() - then


if not x_prob is None:
    x_prob_data = x_prob.cpu().data.numpy()
    output_data =  [item.cpu().data.numpy() for item in outputs]
else:
    x_prob_data = None
    output_data = []

url = generate_report(x = x, p = p, h = h, out_dir = opt.out, url_prefix = opt.prefix, info = info, loss1 = loss_hists1, loss2 = loss_hists2, scales = scales, efdr = efdr, x_prob = x_prob_data, outputs = output_data, grids = grids)

print(url)

