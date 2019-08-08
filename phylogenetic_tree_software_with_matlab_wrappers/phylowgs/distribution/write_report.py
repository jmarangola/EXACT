from __future__ import print_function
import argparse
import numpy as np
import os
from scipy import stats
from pwgsresults.result_loader import ResultLoader

def round_to_int(arr, dtype=np.int64):
  '''Round each array element to the nearest integer, while distributing the
  rounding errors equitably amongst members.'''
  rounded = np.rint(arr)
  rerr = np.sum(rounded - arr)
  assert np.isclose(np.rint(rerr), rerr), '%s %s' % (np.rint(rerr), rerr)

  # Correct rounding error by subtracting 1 from the largest node, then
  # moving on to the next and continuing until no error remains. Assuming
  # that elements in arr sum to an integer, the accumulated rounding error
  # will always be an integer, and will always be <= 0.5*len(arr).
  biggest_idxs = list(np.argsort(rounded))
  while not np.isclose(rerr, 0):
    biggest_idx = biggest_idxs.pop()
    if rerr > 0:
      rounded[biggest_idx] -= 1
    else:
      rounded[biggest_idx] += 1
    rerr = np.sum(rounded - arr)

  rounded = rounded.astype(dtype)
  assert np.isclose(np.sum(arr), np.sum(rounded))
  return rounded

class SubcloneStatsComputer(object):
  def __init__(self, tree_summary):
    self._tree_summary = tree_summary
    # These parameters can be accessed by client code.
    self.cancer_pops = None
    self.cellularity = None
    self.phis = None

  def calc(self):
    self._calc_global_stats()
    self._calc_pop_stats()

  def _find_clonal_node(self, pops):
    indices = [k for k in pops.keys() if k > 0]
    return min(indices)

  def _calc_global_stats(self):
    cancer_pop_counts = []
    cellularities = []

    for tree_idx, tree_features in self._tree_summary.items():
      pops = tree_features['populations']

      # Tree may not have any canceerous nodes left after removing nodes with <
      # 3 SSMs.  (Note that non-cancerous root node will always remain,
      # however.) In such cases, skip this tree.
      if len(pops) == 1:
        continue

      # Subtract one to eliminate non-cancerous root node.
      cancer_pop_counts.append(len(pops) - 1)
      clonal_idx = self._find_clonal_node(pops)
      # clonal_idx should always be 1, given the renumbering I do to remove
      # nonexistent nodes.
      assert clonal_idx == 1
      cellularities.append(np.mean(pops[clonal_idx]['cellular_prevalence']))

    self.cancer_pops = intmode(cancer_pop_counts)
    self.cellularity = np.mean(cellularities)

  def _calc_pop_stats(self):
    K = self.cancer_pops
    phis_sum = np.zeros(K)
    trees_examined = 0

    for tree in self._tree_summary.values():
      pops = tree['populations']
      if len(pops) - 1 != K:
        continue
      # TODO: extend the format to handle cellular prevalences for multi-sample
      # data. Current mean-taking behaviour is stupid.
      phis = [np.mean(pops[pidx]['cellular_prevalence']) for pidx in pops.keys() if pidx != 0]
      phis = np.array(sorted(phis, reverse=True))
      # Map nodes to one another by rank of descending cellular prevalence.
      # This behaviour isn't ideal, but it's better than previous behaviour,
      # when we just relied on the given node indices (assigned in JSON-writing
      # code via depth-first traversal) as given.
      phis_sum += phis
      trees_examined += 1

    self.phis = phis_sum / trees_examined

class ClusterMembershipComputer(object):
  def __init__(self, loader, subclone_stats):
    self._loader = loader
    self._subclone_stats = subclone_stats

  def calc(self):
    K = self._subclone_stats.cancer_pops
    num_ssms = self._loader.num_ssms
    ssm_cp = np.zeros(num_ssms)
    pop_ssm_count = np.zeros(K)
    trees_examined = 0

    for tree_idx, mut_assignments in self._loader.load_all_mut_assignments():
      pops = self._loader.tree_summary[tree_idx]['populations']
      num_cancer_pops = len(pops) - 1
      if num_cancer_pops != K:
        continue

      pop_idxs = [pidx for pidx in pops.keys() if pidx != 0]
      assert len(pop_idxs) == num_cancer_pops == K
      assert set(pop_idxs) == set(range(1, K + 1))
      pop_idxs = sorted(pop_idxs, key = lambda P: pops[P]['cellular_prevalence'], reverse = True)
      for rank, pop_idx in enumerate(pop_idxs):
        pop_ssms = mut_assignments[pop_idx]['ssms']
        ssm_ids = [int(ssm[1:]) for ssm in pop_ssms]
        pop_cp = pops[pop_idx]['cellular_prevalence']
        ssm_cp[ssm_ids] += pop_cp
        pop_ssm_count[rank] += len(ssm_ids)
      trees_examined += 1

    assert np.array_equal(np.sum(pop_ssm_count), num_ssms * trees_examined)
    ssm_cp        /= trees_examined
    pop_ssm_count = round_to_int(pop_ssm_count / trees_examined)

    assignments = np.zeros(num_ssms, dtype=np.int64)
    ordered_ssm_idxs = np.argsort(-ssm_cp) # Order by descending CP
    cumssms = np.cumsum(pop_ssm_count)
    for I in range(len(cumssms) - 1):
      # Don't need to process cluster zero, since its SSMs will already be
      # assigned to zero, given that all SSMs are assigned to zero by default.
      start, end = cumssms[I], cumssms[I + 1]
      ssmidxs = ordered_ssm_idxs[start:end]
      assignments[ssmidxs] = I + 1

    for cidx in range(K):
      assert np.sum(assignments == cidx) == pop_ssm_count[cidx]
    return (assignments, pop_ssm_count)

class SsmAssignmentComputer(object):
  def __init__(self, loader):
    self._loader = loader

  def compute_ssm_assignments(self):
    num_ssms = self._loader.num_ssms
    for tree_idx, mut_assignments in self._loader.load_all_mut_assignments():
      num_pops = len(mut_assignments)
      ssm_ass = np.zeros((num_ssms, num_pops))
      for subclone_idx, muts in mut_assignments.items():
        ssm_ids = [int(ssm[1:]) for ssm in muts['ssms']]
        ssm_ass[ssm_ids, subclone_idx - 1] = 1.0
      assert np.array_equal(np.sum(ssm_ass, axis=1), np.ones(ssm_ass.shape[0]))
      yield (tree_idx, ssm_ass)

class CoassignmentComputer(object):
  def __init__(self, loader):
    self._loader = loader

  def compute_coassignments(self):
    num_ssms = self._loader.num_ssms
    coass = np.zeros((num_ssms, num_ssms))
    num_trees = 0
    ssm_ass = SsmAssignmentComputer(self._loader)

    for tree_idx, ssm_ass in ssm_ass.compute_ssm_assignments():
      num_trees += 1
      ssm_ass_sq = np.dot(ssm_ass, ssm_ass.T)
      assert np.array_equal(np.diag(ssm_ass_sq), np.ones(ssm_ass_sq.shape[0]))
      coass += ssm_ass_sq
    coass /= num_trees
    return coass

class SsmRelationComputer(object):
  def __init__(self, loader):
    self._loader = loader

  def _determine_node_ancestry(self, tree_structure, num_pops):
    node_ancestry = np.zeros((num_pops, num_pops))
    def _mark_desc(par, desc):
      # Ignore root when calculating matrix. It's of no interest as it has no
      # SSMs.
      if par == 0:
        return
      for descendant in desc:
        node_ancestry[par - 1, descendant - 1] = 1
        if descendant in tree_structure:
          _mark_desc(par, tree_structure[descendant])

    for parent, children in tree_structure.items():
      _mark_desc(parent, children)
    return node_ancestry

  def compute_ancestor_desc(self):
    ssm_ass = SsmAssignmentComputer(self._loader)
    num_ssms = self._loader.num_ssms
    ancestor_desc = np.zeros((num_ssms, num_ssms))
    num_trees = 0

    for tree_idx, ssm_ass in ssm_ass.compute_ssm_assignments():
      num_trees += 1
      tree_summ = self._loader.tree_summary[tree_idx]
      structure = tree_summ['structure']
      num_pops = ssm_ass.shape[1]
      node_ancestry = self._determine_node_ancestry(structure, num_pops)

      ssm_ancestry = np.dot(ssm_ass, node_ancestry)
      # ADM: ancestor-descendant matrix
      tree_adm = np.dot(ssm_ancestry, ssm_ass.T)
      assert np.array_equal(np.diag(tree_adm), np.zeros(tree_adm.shape[0]))
      ancestor_desc += tree_adm

    ancestor_desc /= num_trees
    return ancestor_desc

class NodeRelationComputer(object):
  def __init__(self, loader, num_cancer_pops):
    self._loader = loader
    self._num_cancer_pops = num_cancer_pops

  def compute_relations(self):
    adj_matrix = np.zeros((self._num_cancer_pops + 1, self._num_cancer_pops + 1))

    for tree_idx, tree_features in self._loader.tree_summary.items():
      structure = tree_features['structure']
      # Only examine populations with mode number of nodes.
      if len(tree_features['populations']) - 1 != self._num_cancer_pops:
        continue
      for parent, children in tree_features['structure'].items():
        for child in children:
          adj_matrix[parent, child] += 1.0

    most_common_parents = adj_matrix.argmax(axis=0)
    return most_common_parents

def intmode(iter):
  return int(stats.mode(iter)[0][0])

def main():
  parser = argparse.ArgumentParser(
    description='Write SMC-Het Challenge outputs',
		formatter_class=argparse.ArgumentDefaultsHelpFormatter,
  )
  parser.add_argument('tree_summary',
    help='JSON-formatted tree summaries')
  parser.add_argument('mutation_list',
    help='JSON-formatted list of mutations')
  parser.add_argument('mutation_assignment',
    help='JSON-formatted list of SSMs and CNVs assigned to each subclone')
  parser.add_argument('output_dir',
    help='Directory in which to save Challenge outputs')
  args = parser.parse_args()

  loader = ResultLoader(args.tree_summary, args.mutation_list, args.mutation_assignment)
  outputs_to_write = set(('1A', '1B', '1C', '2A', '2B', '3A', '3B'))

  # ssc is used for outputs 1A, 1B, 1C, 2A, and 3A.
  if len(set(('1A', '1B', '1C', '2A', '3A')) & outputs_to_write) > 0:
    ssc = SubcloneStatsComputer(loader.tree_summary)
    ssc.calc()

  if '1A' in outputs_to_write:
    with open(os.path.join(args.output_dir, '1A.txt'), 'w') as outf:
      print(ssc.cellularity, file=outf)
  if '1B' in outputs_to_write:
    with open(os.path.join(args.output_dir, '1B.txt'), 'w') as outf:
      print(ssc.cancer_pops, file=outf)

  if '1C' in outputs_to_write or '2A' in outputs_to_write:
    cmc = ClusterMembershipComputer(loader, ssc)
    ssm_ass, num_ssms = cmc.calc()

    if '1C' in outputs_to_write:
      with open(os.path.join(args.output_dir, '1C.txt'), 'w') as outf:
        for cluster_num, phi in enumerate(ssc.phis):
          # If you want the number of SSMs in the cluster to match the mutation
          # assignments in 2A, you can do this:
          #ssms_in_cluster = np.sum(ssm_ass == cluster_num)

          # But we don't care about this matching at the moment, so we'll
          # compute our posterior summary without the number of mutations
          # reported in 1C and the counts from 2A needing to match.
          ssms_in_cluster = num_ssms[cluster_num]
          print(cluster_num + 1, ssms_in_cluster, phi, sep='\t', file=outf)

    if '2A' in outputs_to_write:
      with open(os.path.join(args.output_dir, '2A.txt'), 'w') as outf:
        for ssm_idx, cluster in enumerate(ssm_ass):
          print(cluster + 1, file=outf)

  if '2B' in outputs_to_write:
    coassc = CoassignmentComputer(loader)
    coass_matrix = coassc.compute_coassignments()
    np.savetxt(os.path.join(args.output_dir, '2B.txt.gz'), coass_matrix)

  if '3A' in outputs_to_write:
    nrc = NodeRelationComputer(loader, ssc.cancer_pops)
    parents = nrc.compute_relations()
    with open(os.path.join(args.output_dir, '3A.txt'), 'w') as outf:
      for child, parent in enumerate(parents):
        # Root node doesn't have a parent, so this value will be meaningless.
        if child == 0:
          continue
        print(child, parent, sep='\t', file=outf)

  if '3B' in outputs_to_write:
    ssmrc = SsmRelationComputer(loader)
    anc_desc = ssmrc.compute_ancestor_desc()
    np.savetxt(os.path.join(args.output_dir, '3B.txt.gz'), anc_desc)

if __name__ == '__main__':
  main()
